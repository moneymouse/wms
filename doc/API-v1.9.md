# API v1.9：纸单回传与核对入库

日期：2026-10-01。新增独立流程，不改变订单、出库、运单或财务接口。

正式接入与当前使用方式见 [API v1.12](API-v1.12.md)。本文保留最初接口设计记录。

所有接口沿用 `x-token` JWT 认证，响应为 `{code, data?, msg?}`。图片接口直接返回图像。提交和查看允许 `worker`（兼容 `employee`）、`admin`、`store_manager`、`salesperson`、`clerk`；只有后四种角色可保存草稿、识别和确认。操作工的列表、详情、图片只能访问本人回传，服务端均执行检查。

## 回传记录

`Intake`：`uid`、`submitted_by`、`submitted_by_name`、`created_at`、`operation_at`（可选现场时间）、`mark_hint`、`note`、`status`（`pending` / `confirmed`）、`draft`、`version`、`photos`、`confirmed_by`、`confirmed_at`、`packing_list_uid`、`recognition_status`、`recognition_error`、`recognition_result`。

草稿格式：

```json
{
  "mark": "ABC-001",
  "boxes": [
    {"box_number": 7, "item_name": "鞋", "count": 3, "weight": 1.5},
    {"box_number": 9, "item_name": "衣服", "count": 4, "weight": 2.25}
  ]
}
```

每张照片元数据为 `{uid, filename, mime_type, url}`。`url` 必须附带 `x-token` 获取，前端以鉴权 `fetch` 转 blob 显示。照片存于 `paper_intake_photos`，列表不读取照片二进制内容。图片不暴露于公开 `static` 路径。

## 接口

| 方法与路径 | 参数及行为 |
| --- | --- |
| `POST /api/intakes` | `multipart/form-data`：`photos` 多文件；可选 `mark_hint`、`note`、`operation_at`。只上传照片即可成功。实际HTTP 201，返回完整记录。 |
| `GET /api/intakes` | 可选 `status=pending\|confirmed`、`packing_list_uid`（精确查找正式装箱单的来源回传）、`page=1`、`page_size=20`（最多100）。返回 `data:{items,total,page,page_size}`。 |
| `GET /api/intakes/:uid` | 返回完整记录。 |
| `GET /api/intakes/:uid/photos/:photo_uid` | 鉴权读取原图，`Cache-Control: private, no-store`。 |
| `PUT /api/intakes/:uid/draft` | JSON `{version,draft}`；可以保存空唛头、空行、缺件数或重量的草稿。成功返回递增版本的记录。 |
| `POST /api/intakes/:uid/confirm` | JSON `{version}`；确认最新已保存草稿，返回完整记录及 `packing_list_uid`。重复确认返回原结果。 |
| `POST /api/intakes/:uid/recognize` | JSON `{version}`；启动后台识别，HTTP 202 返回记录，轮询详情读取结果。 |

上传限制：1—8张；每张最大10MB；JPEG、PNG、WebP，验证实际图片内容；整个请求不超过81MB。唛头提示最多64字，备注512字，现场时间为ISO日期时间（兼容 `YYYY-MM-DD HH:mm:ss`）。失败不创建回传记录。

## 核对与确认

草稿最多500箱；保存阶段保留未完整字段。确认要求唛头、至少一箱、每箱品名、正整数件数、有限正数重量、唯一正整数箱号。现有箱号字段为整数，第一版明确拒绝字母和前导零箱号，避免静默改号。保留不连续纸单箱号，不按行号重排。

唛头沿用既有大写规范。已有相同唛头（包含已归档记录）返回409并说明冲突，不自动改名或合并。成功时一次事务新建一个 `completed` 装箱单及所有箱子；箱子为 `status=0`、未关联订单、无运单、无出库时间，仅登记 `create_date`。正式箱子件数同时写入 `count`、`piece_count`，品名同时写入现有相关字段。任何箱子失败会整体回滚。

服务使用行锁和SQLAlchemy版本检查保护竞争写入。草稿和识别状态更新递增 `version`；过期写入返回409，前端须保留未保存内容供用户核对。已确认草稿不可修改。重复确认不创建新单，即使请求版本是确认前的旧版本也返回相同装箱单UID。

原图与现场时间通过回传记录持续追溯。私有图片不写入旧装箱单 `photos` 公共图片数组，原图查看入口为纸单回传详情 `/intakes/:uid`，生成装箱单详情为 `/packing-lists/:uid`。

已知正式装箱单UID可通过 `GET /api/intakes?packing_list_uid=:uid` 查到来源回传UID和原图元数据，依然遵守操作工仅看本人的权限。旧装箱单详情页面第一版保留现有展示，来源图片入口在纸单回传页面。

## DeepSeek识别

适配入口为 `services/intake_recognition.py` 的 `recognize_paper_photos(images, mark_hint='')`，输入受控图片字节，输出 `{mark,boxes,warnings,provider,model}`。DeepSeek 配置只读取后端 `env.toml` 顶层的 `deepseek_api_key`、`deepseek_base_url`、`deepseek_model`、`deepseek_timeout_seconds`，每次调用重新读取，不再读取环境变量或后端 `.env`。文件或字段缺失时使用默认值：密钥为空、地址为 `https://api.deepseek.com`、模型为 `deepseek-flash`、超时为 90 秒；空密钥禁用识别和地址解析。

新部署先执行 `cp env.toml.example env.toml`，再填写 `deepseek_api_key = "实际密钥"`。Docker Compose 在运行时只读挂载该文件；真实配置不提交到 Git，也不打包进镜像。

识别限制最多8张、单张10MB、合计24MB；总大小超过识别限制仍可人工核对，识别失败说明原因。未配置密钥、模型不支持图片、服务请求或返回结构失败都显示真实错误，不产生示例识别结果。

`recognition_status` 为 `idle`、`running`、`succeeded`、`failed`。后台只保存 `recognition_result` 候选，不直接修改人工草稿或库存。用户明确采用候选后再保存和确认。识别结果到达时前端必须比较服务器草稿与本地已保存草稿，出现其他人修改时要求刷新，不能用识别状态的新版本覆盖旧内容。

第一版后台任务使用进程内线程；重启不会恢复任务。超过5分钟的任务在读取详情时标记失败，允许重试；迟到的旧任务通过任务UID判断失效，不覆盖新任务。此机制适合本地第一版体验，生产部署前应改为持久队列。

## 校验与本地测试

常见错误：401未登录；403权限不足；404记录或照片不存在；400图片/草稿/确认字段无效；409版本、已确认修改或唛头冲突；413请求太大；500操作失败。失败响应不宣称已入库，刷新后可以确认实际状态。

新增Alembic版本 `df4a5b6c7d8e`，父版本 `ce3f4a5b6c7d`，新增 `paper_intakes` 和 `paper_intake_photos`。正式数据库接入需按项目迁移流程执行，本次本地体验不连接业务数据库。

后端测试使用独立Flask应用与SQLite内存数据库，不导入含备份和管理员初始化副作用的 `app.py`：

```sh
zsh -ic 'condactivate && conda activate WMS && pytest --confcutdir=tests/intake tests/intake -q'
```

前端 `src/pages/intakes.test.js` 覆盖上传、草稿、确认、识别与权限等交互。流程已接入正式 Flask 与 React 入口，数据库迁移和部署方式见 [API v1.12](API-v1.12.md)。
