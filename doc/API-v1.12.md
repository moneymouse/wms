# API v1.12：纸质装箱单正式接入

日期：2026-10-02。纸单上传、自动识别、工人绑定及核对确认已纳入主系统，不再通过独立演示服务启动。业务字段延续 [API v1.11](API-v1.11.md)。

## 正式入口

主后端 `app.py` 注册 `intake_bp`，WSGI 通过现有 `wsgi:application` 加载；用户通过正常登录获取 JWT，纸单 API 沿用 `x-token` 和角色校验。

React 创建装箱单页面 `/packing-list/new` 提供手动录入、拍照上传和 A4 空白模板下载。工人在 `/packing-lists` 查看自己创建的两种来源的装箱单；文员从装箱单列表右侧“待核对纸质单?”进入 `/intakes` 及核对页。界面保留白色背景、页面留白及无图标的“提交照片”按钮。

确认前选择批准的工人账户；确认事务为每箱写入工人关联，装箱单创建人取原上传人，审核人单独记录。识别结果直接显示在可编辑核对表中，疑点集中在 132px 高的滚动区域，确认主按钮会先保存修改。

有纸单上传、核对或来源装箱单引用的账号，以及有纸单来源的装箱单，硬删除返回 409，避免破坏原图和来源追溯；装箱单仍可归档。无纸单引用的原有删除流程保持可用。

## 正式模板下载

`GET /api/intakes/template` 允许纸单提交角色，返回认证 PDF 下载：

- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename=paper-packing-list-a4.pdf`
- `Cache-Control: private, no-store`

模板位于 `static/templates/paper-packing-list-a4.pdf`，构建时纳入后端镜像。接口读取已生成的模板，不依赖项目外的输出目录或运行时字体。可用 `scripts/generate_paper_intake_template.py` 更新静态文件，重新生成时需 ReportLab 和中文 TTF/TTC 字体。

无认证返回 401、角色不允许返回 403，模板文件缺失返回 JSON 503。前端仅在收到非空 PDF 时下载，错误响应不会作为文件保存。

## 运行配置与迁移

照片合计不超过 24MB，multipart 请求不超过 25MB；生产、预发和测试 Nginx 的请求上限已同步为 25MB。Docker 已包含 Pillow、ReportLab 和 Alembic，无新增运行时包。

识别服务和地址解析共用后端 `env.toml`。新部署先执行 `cp env.toml.example env.toml`，在文件顶层配置 `deepseek_api_key`、`deepseek_base_url`、`deepseek_model`、`deepseek_timeout_seconds`；每次调用重新读取，不再读取环境变量或后端 `.env`。文件或字段缺失时使用默认值：空密钥、`https://api.deepseek.com`、`deepseek-flash`、90 秒；空密钥禁用识别和地址解析。Docker Compose 在运行时只读挂载 `env.toml`，真实配置不提交到 Git，也不打包进镜像。数据库等现有 Docker 环境配置沿用 `BK.env`（预发 `PRE_BK.env`）。

本功能的数据库 head 为 `df4a5b6c7d8e`，父版本 `ce3f4a5b6c7d`，新增 `paper_intakes` 和 `paper_intake_photos`。有现有 Alembic 版本的数据库，执行 `alembic upgrade head`。Docker Compose 默认不自动运行迁移，正式更新命令为：

```sh
# 前端目录：生成 Nginx 所使用的正式 build
npm run build

# 后端目录：使用已配置的正式数据库环境
docker compose -f docker-compose.yml build backend
docker compose -f docker-compose.yml run --rm --entrypoint alembic backend upgrade head
docker compose -f docker-compose.yml up -d backend nginx
```

有业务表但没有 `alembic_version` 的旧数据库，必须先核验实际 schema 对应的具体 revision。不能直接 `stamp head` 跳过新表；启动脚本在这种情况要求已核验的 `ALEMBIC_BASELINE_REVISION`，记录基线后执行升级。空库和已版本化数据库按正常迁移链升级。

后台识别沿用进程内线程，原图、草稿和任务状态持久化在正式数据库；服务重启或超过五分钟后，核对列表/详情会标记超时，核对人员可重试。失败不会删除照片，也不会自动创建库存。

## 演示版本退役

已移除独立演示脚本、示例身份登录与角色切换、演示图片及健康检查接口，停止原演示服务并清理专用临时构建、运行目录和字节码。旧运行数据曾完成 SQLite 完整性检查并归档；2026-10-06 按用户要求删除本地演示数据及归档，不作为正式账户或库存的导入来源。原交付 PDF 和正式静态模板保留。

## 验证

后端纸单套件 144 项通过，包含正式 `app.py` 的真实密码登录 → JWT → 上传 → 文员核对确认 → 工人本人清单、模板下载/缺失错误、权限隔离、真实临时 Alembic 升级与回退、MySQL 离线 DDL、启动迁移分支及启用真实外键的删除/归档边界验证。前端 44 项定向测试、ESLint 及正常 `npm run build` 通过，仅保留其他既有页面警告。

验证使用隔离数据库，当前本机 Docker daemon 未运行；正式数据库升级和服务发布需要在配置齐全、数据库可达的运行环境执行。
