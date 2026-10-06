# API v1.27：装箱单出货确认单与草稿

允许管理员、店长、业务员、文员使用；业务员和文员访问自己的草稿，管理员和店长可访问全部草稿。打印不修改箱子分配、出库状态、订单、报价或财务数据。

v1.30 起前端编辑使用独立页面 `/shipping-confirmation-drafts` 及 `/shipping-confirmation-drafts/<uid>`，从装箱单列表标题右侧“出货确认单草稿”或 PDF 按钮进入，详细交互见 [API v1.30](API-v1.30-uploader-check-and-shipping-drafts-page.md)。

## 箱子选择与直接打印

`POST /api/packing-lists/shipping-confirmation/boxes`：请求 `{ "cargo_uids": ["箱子UID"] }`，返回 `{code:200,data:{items:[...]}}`。条目包含 `cargo_uid`、`packing_list_uid`、`list_number`、`box_number`、`tag`、`transfer_id`、`weight`、`customer_id`、`customer_name`、`target_order_uid`、`order_id`、`agent_name`、`remarks`、`available`。未分配订单的箱子也可使用；已分配箱子的初始代理依据订单运输渠道的渠道组（沿用原映射）。

`POST /api/packing-lists/shipping-confirmation/pdf`：请求 `{ "entries": [{"cargo_uid":"箱子UID","agent_name":"手填代理","remarks":"地址、邮编等"}] }`，返回 PDF。代理和备注只用于确认单，不写回渠道或订单。按客户、代理、备注分组，允许一个分组包含多个装箱单，抬头列出来源装箱单；沿用 A4 两列裁切版式。

## 草稿

- `GET /api/shipping-confirmation-drafts`：`data.items` 为草稿摘要，按更新时间倒序。
- `POST /api/shipping-confirmation-drafts`：`{title,entries}` 创建。
- `GET /api/shipping-confirmation-drafts/<uid>`：读取和重新打开。
- `PUT /api/shipping-confirmation-drafts/<uid>`：`{title,entries,expected_version}` 完整替换选择和打印信息；前端追加时合并已有箱子并去重。
- `DELETE /api/shipping-confirmation-drafts/<uid>`：`{expected_version}` 归档草稿。
- `POST /api/shipping-confirmation-drafts/<uid>/pdf`：`{expected_version}` 打印已保存版本。

摘要包含 `uid,title,version,creator_id,created_at,updated_at,box_count`；详细响应额外包含 `entries`。所有 JSON 成功响应为 `{code:200,data:...}`。新草稿版本为 1，每次保存递增。版本不符返回 409，保留已保存内容。允许保存空草稿，但打印必须有箱子。

每份草稿最多 500 箱，箱子不可重复，代理最多 128 字，备注最多 2000 字。保存验证箱子和装箱单仍存在且未归档。重新打开时获取最新唛头、原单号和订单归属；已删除或归档的箱子显示 `available:false`，保留来源快照。打印整批拒绝无效箱子，必须移除后重试，避免少印。过长抬头导致无法排版时返回 400。

PDF 响应为 `application/pdf`，附件名 `shipping-confirmation.pdf`，`Cache-Control: private, no-store`。JSON 错误沿用 `{code,msg}`，包括 400 验证、403 权限、404 无效草稿/箱子、409 版本冲突。

数据库迁移：`20261006_68d3e4f5a6b7_shipping_confirmation_drafts.py` 新增 `shipping_confirmation_drafts`，依赖收据箱子备注迁移 `57c2d3e4f5a6`。MySQL 的草稿内容及业务审计快照使用 LONGTEXT，支持大批量箱子和备注；降级删除草稿表时保留已扩容的审计存储，保护既有收据历史。草稿创建、保存和删除记录业务审计；未改变出货事实。
