# API v1.46：异常订单与跟进

订单或其中的包裹可以登记异常理由。登记、追加登记历史和通知对应业务员在同一事务内完成。第一版由当前负责业务员手动标记已解决，物流恢复正常不会自动关闭异常；阅读收件箱通知也不会解决异常。

## 身份和访问范围

所有人工接口使用 `x-token`，服务重新核对员工审批状态和数据库中的角色。业务员只可登记、查看、跟进和解决本人负责订单的异常。管理员列表默认本人业务身份，可切换查看任意业务员；其他业务员的异常只读。文员可登记有有效负责人的订单异常，不能读取其他业务员的列表和跟进历史。

权限使用订单当前 `salesman_id`，变更负责人后，原负责人不能再读取或跟进该订单异常，新负责人可以处理。登记时的订单、包裹、人员标识和姓名保存为快照；原有业务实体硬删除后历史事实仍保留，但已删除订单的异常不能再由这些接口读取。订单负责人须已审批且有业务员或管理员角色，没有有效负责人的登记返回 409。

## 统一响应

成功：`{"code":200,"data":...}`。失败：`{"code":400|401|403|404|409,"msg":"..."}`，HTTP 状态同 `code`。跨业务员详情与不存在的异常均返回 404。

异常摘要字段：`uid, order_uid, order_id, cargo_uid, origin_id, transfer_id, waybill_id, salesman_id, salesman_name, reason, source, status, created_at, updated_at, resolved_at, can_followup, can_resolve`。`source` 为 `manual` 或 `17track`，`status` 为 `open` 或 `resolved`。业务员姓名和编号反映当前订单归属；其余业务标识为登记时快照；`transfer_id` 为包裹原单号，`origin_id` 为内部原始标识。

详情另含 `history`，按时间升序。历史字段：`uid, action, type, note, source, actor_id, actor_name, tracking_status, created_at`。`action/type` 同值：`registered`、`followup`、`resolved`。自动登记人员为空，来源为 `17track`。

## 人工登记

`POST /api/order-exceptions`

```json
{"order_uid":"订单内部 UID","cargo_uid":"可选包裹内部 UID","reason":"异常理由","event_key":"本次操作稳定 UUID"}
```

`reason` 不能为空，最多 2000 字；`event_key` 为最多 128 字的非空字符串。省略 `cargo_uid` 表示订单级异常。包裹必须未归档且属于指定订单。有该案例读取权限的员工响应为异常摘要；没有读取权限的登记者（如文员登记其他业务员的单）只收到 `{uid, order_uid, cargo_uid}` 登记回执，不能获得已有案例的理由、时间、来源或跟进历史。

同一订单/包裹范围的未解决异常合并为同一案例，不同登记事件追加历史并发送新的通知。同一员工重试同一 `event_key` 和内容只产生一次历史和通知；内容冲突返回 409。案例解决后重复旧事件不会重开，新的登记事件会建立新的案例。

通知使用现有消息服务，处理路径为 `/order-exceptions?exception_uid=<uid>`，`business_type=order_exception`，`business_id=<uid>`。

## 查询

`GET /api/order-exceptions?status=all&page=1&page_size=20`

`status` 为 `all/open/resolved`，`page_size` 最大 100。管理员可增加 `salesman_id=<员工编号>`；其他角色指定该参数返回 403。响应 `data` 为：

```json
{"items":[],"total":0,"page":1,"page_size":20,"salesman_id":1}
```

`GET /api/order-exceptions/<uid>` 返回详情。`GET /api/order-exceptions/salespeople` 仅管理员可用，返回已审批业务员以及当前管理员的简单选择项 `[{"id":1,"name":"员工姓名"}]`。

## 记录跟进和手动解决

`POST /api/order-exceptions/<uid>/followups`

```json
{"note":"本次跟进过程","event_key":"本次操作稳定 UUID"}
```

`POST /api/order-exceptions/<uid>/resolve`

```json
{"note":"解决说明","event_key":"本次操作稳定 UUID"}
```

跟进说明最多 2000 字且不能为空；解决说明可省略，默认“手动标记已解决”。返回包含完整历史的详情。仅当前负责业务员可操作，包括自己负责该单的管理员。相同操作事件和内容重试不追加历史、不改变第一次解决时间；事件内容冲突返回 409，已解决案例不能追加新的跟进或再次解决。

## 服务层共用原语

`register_exception(session, order_uid=..., cargo_uid=None, reason=..., source=..., event_key=..., actor=None, tracking_status=None, expected_waybill_id=None)` 返回异常 ORM 记录，不提交、回滚或关闭调用者事务。人工来源必须提供认证 actor；17TRACK 来源由验签后的 webhook 调用。`expected_waybill_id` 用于取得订单和包裹锁后检查回调的转单号是否仍匹配，避免并发换号误登记。

订单锁串行化负责人更改、登记和解决。历史持久事件唯一约束与通知事件唯一约束共同防重复；通知失败时该次案例变更及登记历史全部回滚，重试可重新完成。物流状态不覆盖现有货物仓库业务状态。

## 17TRACK v2.2 webhook

`POST /api/webhooks/17track` 不使用员工 JWT，须提供请求头 `sign`。沿用现有 `env.toml` 的 `17track_token`，按 [17TRACK v2.2 官方文档](https://asset.17track.net/api/document/v2.2_en/index.html) 计算 `SHA256(原始 UTF-8 正文 + "/" + API key)`，以常量时间比较校验；不能先解析再序列化正文进行验签。缺少密钥时拒绝处理并返回 503，不会以无验签方式接受回调。

处理 `event=TRACKING_UPDATED`；官方详细回调格式的 `data` 为单条物流记录，亦兼容官方 quick-start 中的 `data.accepted` 数组格式（最多 40 条）。以 `data.track_info.latest_status.status == "Exception"` 为异常，子状态说明沿用既有中文映射。`DeliveryFailure`、`Expired`、清关需资料等独立状态不自动扩大为异常范围。

`data.tag` 必须匹配当前未归档包裹 UID，`data.number` 必须与其当前转单号相符，并复核所属订单、锁后转单号和有效业务负责人。未知、已移除或过期包裹注册被忽略并返回 200，不会根据相同转单号猜测另一包裹。其他事件被确认接收且不会清空已有物流；非 Exception 状态保存本地物流与接收历史，但不创建或关闭异常。完整物流保存与本地读取规则见 [API v1.47](API-v1.47-local-parcel-tracking.md)。

验签后对每条完整物流记录的规范 JSON 生成稳定摘要，作为持久登记事件键。因此相同内容重发（含 JSON 空白或对象键顺序改变）只追加一次历史并通知一次；解决后同一旧事件也不重开。新的不同异常事件成为当前物流快照时，可追加到现有未解决案例，或在已解决后建立新案例；明显更旧的回调仅保留接收历史，不覆盖当前物流或新建异常。官方没有唯一投递 ID 或回调顺序保证；内容不同的更新被视为不同事件。

所有批量物流快照、接收历史、异常登记、异常历史和消息一并提交后才返回 HTTP 200。签名不符返回 401，格式错误 400，业务关联冲突 409，数据库/通知失败 503；正文上限 2 MiB，超出返回 413。失败不保留“已处理”标记，可正确重试。官方只将 HTTP 200 视为成功，失败重试间隔为 600、1800、3600 秒。日志和错误响应不含密钥、签名或完整回调正文。

回调地址须在预发部署确认、HTTPS 和现有 17TRACK 账户设置核对后再配置。本次本地开发不修改账户回调设置或真实物流登记。
