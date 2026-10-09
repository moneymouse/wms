# API v1.36：纸单照片文件存储与存储管理

纸单照片改存持久化文件目录，`paper_intake_photos` 仅保存 `storage_path`、`size_bytes`、`sha256` 及原有文件名、格式、来源等元数据，移除 `data` 二进制列。图片查看和识别沿用现有接口、鉴权与原始字节，不公开静态文件地址。

默认目录为后端根目录的 `uploads/paper_intakes/`，Docker 中为 `/app/uploads/paper_intakes/`。生产的 `./uploads`、预发布的 `./uploads_pre`、测试的 `./uploads_test` 均挂载到 `/app/uploads`。可用 `PAPER_PHOTO_ROOT` 覆盖目录；迁移和应用必须指向同一持久化目录。文件键为 `<intake_uid>/<photo_uid>.<jpg|png|webp>`，上传文件名不参与磁盘路径。读、写、删均不跟随符号链接。

## 生命周期与一致性

- 上传先验证所有照片和表单，逐张原子写入文件，再提交数据库元数据。提交失败时检查持久化引用后清理未提交文件；提交结果不确定且数据库不可用时保留文件，避免误删已提交原图。
- 识别失败、确认生成装箱单、归档均保留照片。没有自动到期删除。
- 删除装箱单沿用既有出库、费用历史和权限保护；数据库事务先写入 `paper_photo_cleanup` 队列并移除照片引用，提交成功后清理文件。失败可继续原删除请求或在存储管理重试，避免重复写入业务历史。
- 存储管理可以单独删除任意来源的照片；未确认、未出货、未满保留期限和归档来源均允许删除，提前删除时页面提示确认。纸单状态、确认信息、装箱单、箱子、出货及财务记录保留。原图接口随后返回 404，来源照片数组为空。
- 文件删除失败时持久化队列仍在，接口明确返回 `pending_files`；重试对已缺失文件幂等。统计显示实际磁盘文件字节数，包含待清理及尚未完成确认的纸单照片，不包含旧公共照片或其他上传文件。

## 管理接口

全部接口要求 `x-token`，仅 `admin`、`store_manager` 可用。删除和重试写入操作日志。JSON 响应沿用 `{code, data, msg}`；参数错误 400、权限错误 401/403、记录或文件不存在 404、照片损坏或不可安全读取 409、其他失败 500。未满期限不再返回删除限制错误。

| 接口 | 参数 | `data` |
| --- | --- | --- |
| `GET /api/storage/summary` | 无；兼容旧 `days` 参数 | `total_bytes`、`total_files`、`photo_groups`、`pending_cleanup_files`、`pending_cleanup_bytes`；保留旧 `eligible_*` 统计字段兼容 |
| `GET /api/storage/packing-lists` | `page` 默认 1；`page_size` 默认 20、最多 100；`q` 最多 64 字唛头搜索；旧 `days` 仅兼容校验，不筛选列表 | `{items, total, page, page_size}` |
| `GET /api/storage/intakes/:intake_uid/photos` | 无 | `{intake_uid, list_number, photos}` |
| `GET /api/storage/intakes/:intake_uid/photos/:photo_uid` | 无 | 原图字节，正确图片 MIME，`Cache-Control: private, no-store`、`X-Content-Type-Options: nosniff` |
| `DELETE /api/storage/intakes/:intake_uid/photos` | JSON `{}`；兼容 `days` 校验 | `{deleted_files, deleted_bytes, pending_files}` |
| `DELETE /api/storage/packing-lists/:uid/photos` | 兼容旧接口，JSON `{}` 或 `{ "days": 90 }`，不限制删除期限 | `{deleted_files, deleted_bytes, pending_files}` |
| `POST /api/storage/cleanup` | 无 | `{deleted_files, deleted_bytes, pending_files}` |

列表展示所有有照片记录的纸单来源，每个来源一行；未确认、近期上传、未全部出货和归档来源均显示，不按出货状态或天数自动筛选。只应用用户主动输入的唛头搜索和分页。

`items` 每项包含 `{uid, intake_uid, packing_list_uid, list_number, archived, detail_url, detail_label, box_count, last_shipped_at, days_since_shipped, photo_count, photo_bytes, missing_photo_count, can_delete_photos, deletion_warning, cleanup_reason}`。`photo_count` 是照片记录数，`photo_bytes` 是实际安全可读文件的字节数；缺失或不可用的文件仍保留来源行和照片计数，并在 `missing_photo_count` 中标明。正式装箱单优先显示其唛头，未关联正式单时使用纸单当前唛头。未归档正式单的 `detail_url` 指向 `/packing-lists/:uid`，标签为“查看装箱单”；已归档记录显示“已归档”，链接为空。未生成装箱单或来源已删除时也不提供跳转链接。

`can_delete_photos` 对所有来源均为 `true`。`deletion_warning` 是页面删除确认中显示的提示原因；尚未确认、没有关联正式单、没有箱子、存在未出货箱子、缺出货日期或最后出货未满 90 天时非空，达到建议保留期限时为空。归档来源也保留未满期限提示。`cleanup_reason` 与其同值，供旧客户端兼容；`eligible_*` 统计继续表示无需提前删除提示的实际照片文件。旧 `days` 参数接受 1—3650 的整数，仅校验，不改变列表、提示或删除权限。最后出货时间按上海时区计算。

照片查看接口的 `photos` 每项为 `{uid, filename, original_filename, mime_type, url, missing}`，按原上传顺序排列。`filename` 以当前唛头和照片序号命名；`url` 指向上述受鉴权的存储管理原图接口，不包含磁盘路径或公共静态地址。管理员和店长可以查看所有来源的照片，不受原纸单上传者限制，既有 `/api/intakes` 读取权限保持原样。`missing` 表示磁盘文件缺失或无法安全访问；损坏原图返回 409，不返回损坏字节。

按来源清理时锁定纸单和照片记录；兼容装箱单清理接口继续锁定箱子、装箱单、纸单和照片记录。清理队列与移除照片元数据在同一事务提交，文件删除在事务提交后执行。按来源删除及其幂等重试只处理该来源路径下的队列任务，其他来源的待清理文件保持原样。清理照片后纸单状态、识别结果、装箱单、箱子、出货、成本和财务记录继续保留。队列中即使文件已经缺失，仍会统计为待重试任务，实际可释放字节为零。

## 管理页面

管理中心新增“存储管理”模块入口，侧栏也提供入口，路由 `/storage-management`。管理员和店长可查看总磁盘占用、照片文件数、照片来源数和待清理文件。“照片列表”直接展示全部来源的装箱单唛头、照片数、占用空间、照片查看入口及详情跳转链接，只保留主动唛头搜索和分页，移除保留天数筛选和“可清理”预筛选。归档记录标注“已归档”，装箱单详情链接为空，但仍可以查看照片。所有来源均可点击删除；未达到建议保存期限时在确认框提示原因，确认后执行删除。文件删除失败时可手动重试。

## 旧照片迁移及上线

采用三个独立阶段：`export_paper_photos.py` 导出原图、Alembic 修改结构、`import_paper_photo_paths.py` 回填路径。导出阶段不修改数据库；结构迁移不回填路径；回填阶段不删除文件或业务记录。

导出脚本读取 `paper_intake_photos.data` 的原始字节，逐张保存为 `uploads/paper_intakes/<intake_uid>/<photo_uid>.<后缀>`，记录文件大小、SHA256 及原有照片元数据。全部文件重新读取校验成功后，原子发布 `uploads/paper_intakes/.photo-migration-manifest.json`。导出失败不改变数据库；重新导出会核验并复用相同文件，同名内容冲突时停止，保留源数据与现有文件。清单必须与照片文件一起保存。

Alembic 版本 `8af5b6c7d8e9`（父版本 `79e4f5a6b7c8`）有旧照片时会先核对清单、全部照片 UID、原有元数据、源二进制及文件校验值，验证成功后才新增文件元数据列和清理队列表，并移除 `paper_intake_photos.data` 列。该列及其图片二进制是此版本唯一删除的业务数据；照片行、UID、文件名、来源关联、纸单、装箱单、箱子及财务数据均保留。新文件元数据暂为 NULL，等待下一步回填；空照片表可直接迁移。验证失败保留二进制列，此版本需在线执行。

回填脚本重新校验完整清单、数据库 UID 和原有元数据及全部文件，然后写入 `storage_path`、`size_bytes`、`sha256` 并收紧 NOT NULL 约束。同值可以幂等重跑，已有不同元数据拒绝覆盖。导出后新增、删除或修改照片会使迁移或回填拒绝执行，应保持维护窗口，重新导出当前完整数据后再迁移。回填成功前新版后端启动检查会阻止启动。

脚本读取环境变量 `DATABASE_URL`，没有配置时直接报错，不猜测连接真实数据库。默认照片目录固定为后端根目录的 `uploads/paper_intakes/`，不受执行工作目录影响。可用 `--storage-root` / `PAPER_PHOTO_ROOT` 指定照片目录，用 `--manifest` / `PAPER_PHOTO_MANIFEST` 指定清单；三个阶段必须使用同一照片目录和清单，Alembic 通过环境变量读取这些位置。

上线前备份数据库，将新代码同步到服务器并在维护窗口内构建新镜像。生产在服务器后端目录按以下顺序执行；预发布使用 `docker-compose.pre.yml`（启用 TLS 时同时保留 `-f docker-compose.pre.tls.yml`）。MySQL 服务保持运行，其他服务待回填成功后启动：

```sh
compose=(docker compose -f docker-compose.yml --profile mcp)
"${compose[@]}" stop backend mcp
"${compose[@]}" build backend mcp

# 1. 导出并校验照片，数据库保持原样
"${compose[@]}" run --rm --no-deps --entrypoint python backend scripts/export_paper_photos.py

# 2. 校验导出结果，移除图片二进制列
"${compose[@]}" run --rm --no-deps --entrypoint alembic backend upgrade 8af5b6c7d8e9

# 3. 将文件路径、大小、SHA256 回填到数据库
"${compose[@]}" run --rm --no-deps --entrypoint python backend scripts/import_paper_photo_paths.py

"${compose[@]}" up -d backend mcp
```

如果直接在已配置 Python 环境的后端目录运行，同样按以下顺序。`DATABASE_URL` 应事先安全配置在当前进程环境中，照片目录及清单需要映射到应用正式使用的持久化目录：

```sh
python scripts/export_paper_photos.py
alembic upgrade 8af5b6c7d8e9
python scripts/import_paper_photo_paths.py
```

Docker 中这些文件位于 `/app/uploads/paper_intakes/`；生产对应服务器后端目录的 `uploads/paper_intakes/`，预发布对应 `uploads_pre/paper_intakes/`。两个脚本支持 `--help`。

部署脚本单独执行 `--migrate` 只完成结构阶段，旧照片导出或回填缺失时会被迁移或后端启动检查拦截；本次上线应完成上述三个阶段。照片目录已经被部署同步排除，并从 Git 与 Docker 镜像构建上下文排除；后续备份应同时包含数据库元数据和该持久化目录。

降级会先校验当前保留的文件，再恢复旧二进制字段；如果停留在结构迁移后的未回填阶段，则从导出清单读取路径完成恢复。文件或所需清单缺失、存在待清理任务时拒绝降级。主动删除的照片没有对应元数据，降级不会恢复这些照片。

## 验证

使用隔离 SQLite 与临时文件目录覆盖上传/原图/识别/确认/归档/删除、迁移失败与重试、路径安全、清理队列、提交结果不确定时的文件保护；前端覆盖入口权限、统计、筛选、删除确认、错误和重试。未连接或改写生产业务数据库。
