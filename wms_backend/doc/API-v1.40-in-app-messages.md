# API v1.40：站内消息收件箱

站内消息提供独立的发送和接收接口，供财务、物流等业务服务调用。消息保存在数据库中，员工打开通知后可跳转至发送方指定的处理页面。消息已读仅表示员工已阅读，业务是否完成仍由原业务服务决定。财务“退回修改”的自动通知接入见 [API v1.41](API-v1.41-finance-return-messages.md)。

前端通过登录时使用的 `x-token` 请求接口。所有列表、详情、已读操作都由服务器根据当前登录员工确定收件人；请求参数不能指定他人的收件箱，管理员也只能读取自己的消息。员工必须处于 `approved` 状态。

## 消息结构

```json
{
  "uid": "24b5669f663e43fd962f3947b41a8a60",
  "recipient_id": 12,
  "title": "订单需要核对",
  "body": "请核对订单资料，并在对应页面进行处理。",
  "category": "order_review",
  "source_name": "张三",
  "action_path": "/orders/order-123",
  "business_type": "order",
  "business_id": "order-123",
  "created_at": "2026-10-07 16:00:00.000000",
  "read_at": null,
  "is_read": false
}
```

| 字段 | 说明 |
| --- | --- |
| `uid` | 消息唯一编号，32 位字符串 |
| `recipient_id` | 收件员工 ID |
| `title` / `body` | 标题 / 纯文本正文，最长 200 / 10000 字 |
| `category` | 消息分类，最长 64 字；由发送服务定义，例如 `finance_return`、`logistics_exception`、`system` |
| `source_name` | 显示的来源名称，最长 128 字 |
| `action_path` | 可选站内页面路径，可带查询参数；最长 1024 字；禁止外部 URL |
| `business_type` / `business_id` | 可选业务类型 / 业务对象编号，最长 64 / 128 字 |
| `created_at` / `read_at` | 创建 / 首次已读时间，采用现有系统的本地时间格式；未读时 `read_at` 为 `null` |
| `is_read` | 是否已读 |

## 发送消息

`POST /api/messages`

发送员工必须已审批通过，且当前数据库角色包含 `admin`、`store_manager`、`finance`、`clerk` 中至少一个。权限以数据库中的实时角色为准，不使用请求中自行指定的角色或发送人。普通业务员、工人可以读取自己的消息，不能发送跨员工消息。

```json
{
  "recipient_id": 12,
  "title": "订单需要核对",
  "body": "请核对订单资料，并在对应页面进行处理。",
  "category": "order_review",
  "action_path": "/orders/order-123",
  "business_type": "order",
  "business_id": "order-123",
  "event_key": "order:review:order-123:version-2"
}
```

`recipient_id`、`title`、`body`、`event_key` 为必填项。收件人必须存在且已审批通过。`category` 默认为 `system`，其余业务信息可省略。`business_id` 可以传字符串或整数。发送来源 `source_name` 由服务器使用发送员工的数据库姓名填写，客户端传入 `source_name` 会返回 `400`，避免冒用他人的身份。

请求正文必须是 JSON 对象，只允许上述字段。`event_key` 最长 128 字，标识某一次业务事件。服务器按发送员工 ID 隔离事件编号，两个发送人使用相同编号仍是两条独立消息。同一发送人向同一收件人使用相同编号、相同内容重试时返回原消息；重复使用编号但修改内容返回 `409`，新事件应使用新编号。

发送成功返回 `{"code": 200, "data": <消息结构>}`。需要跨服务调用时，可使用具有上述权限的已登录员工或专用服务账号的有效 `x-token` 请求此接口。

## 获取消息列表

`GET /api/messages?page=1&page_size=20&status=all`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `page` | `1` | 从 1 开始的页码；兼容别名 `p` |
| `page_size` | `20` | 正整数，最大 100；兼容别名 `s` |
| `status` | `all` | `all`：全部；`unread`：未读；`read`：已读 |

消息按创建时间倒序排列，同一时间以消息编号倒序排列。`total` 是当前过滤条件下的消息数，`unread_count` 始终是当前员工的全部未读数。列表查询不会标记消息已读。

```json
{
  "code": 200,
  "data": {
    "items": [],
    "total": 0,
    "page": 1,
    "page_size": 20,
    "unread_count": 0
  }
}
```

## 获取未读数量

`GET /api/messages/unread-count`

```json
{"code": 200, "data": {"unread_count": 2}}
```

此接口用于收件箱角标。初期可每 3 分钟请求一次，登录后、窗口重新获得焦点以及阅读消息后主动刷新。

## 获取消息详情

`GET /api/messages/<uid>`

返回 `{"code": 200, "data": <消息结构>}`。读取详情不会自动标记已读，前端在打开成功后明确调用已读接口。

## 标记单条消息已读

`POST /api/messages/<uid>/read`

无需请求正文，返回 `{"code": 200, "data": <消息结构>}`。重复请求保留第一次阅读的 `read_at`，可安全重试。这个操作不会修改账单、订单或任何业务处理状态。

## 全部标记已读

`POST /api/messages/read-all`

无需请求正文。只修改当前员工仍未读的消息。

```json
{"code": 200, "data": {"updated_count": 2, "unread_count": 0}}
```

`updated_count` 是本次改变的消息数。`unread_count` 会重新查询，若此时出现新消息可大于 0。

## 错误响应

| HTTP 状态 | 含义 |
| --- | --- |
| `400` | 请求字段、分页或状态格式无效，或收件员工未审批通过 |
| `401` | 未登录或登录凭证无效 |
| `403` | 无法识别员工，员工不存在、未审批通过，或发送角色无权限 |
| `404` | 发送时收件人不存在；查询时消息不存在或不属于当前员工，后两种情况返回相同错误 |
| `409` | 发送时重复使用事件编号，且消息内容与原消息不同 |

业务错误返回 `{"code": <HTTP 状态>, "msg": "错误说明"}`。认证失败沿用现有认证接口的错误格式。

## 业务服务发送消息

同一后端内部的业务服务，也可以直接调用服务层接口。调用者先按业务规则确认收件人，再使用已有的 SQLAlchemy session 发送：

```python
from services.message_service import send_message

send_message(
    session,
    recipient_id=order.salesman_id,
    title="订单需要核对",
    body="请核对订单资料，并在对应页面进行处理。",
    category="order_review",
    source_name="订单服务",
    action_path=f"/orders/{order.uid}",
    business_type="order",
    business_id=order.uid,
    event_key=f"order:review:{order.uid}:{event_version}",
)
# 与原业务操作在同一个事务中，由原服务统一 session.commit()。
```

`send_message` 返回 `MessageTable` 实例，只将消息写入调用方事务，不会提交该事务。业务操作回滚时，消息也回滚。收件人不存在、字段无效会抛出异常；是否只通知已审批员工由业务发送服务决定。

内部接口的 `event_key` 可选，最长 128 字，必须稳定地标识某次业务事件。数据库保证同一员工、同一事件只生成一条消息，包括并发发送时；不同收件人各自收到独立消息。重复事件若内容不同会抛出 `MessageConflictError`。省略 `event_key` 时每次调用都会创建新消息。内部业务服务应使用业务前缀隔离事件编号，并保留 `http:` 前缀给 HTTP 接口使用。新的业务事件应使用新的编号。

新表 `inbox_messages` 由迁移 `9bf6c7d8e9f0` 创建，其前置版本为 `8af5b6c7d8e9`。部署需按现有 Alembic 流程完成迁移。收件员工删除时，其收件箱消息由数据库级联清理，不会阻止现有员工删除操作，也不会影响其他员工的消息。
