# API v1.22 - 统一客户收付款登记与财务确认

新客户资金登记复用 `FinancePayment`，不根据报价或重量计算登记金额。收付款账户必选；参考订单可不选，可选该客户的空订单、无报价订单或其他业务员订单，仅保存备注快照。真正的订单结算关系由财务后续核销建立。

## 权限与状态

- `salesperson`：只能登记、查看、修改、提交或取消本人创建的客户收付款；不能录入供应商、期初余额，也不能入账、冲销或核销。
- `finance/admin`：可查看全部并财务确认、退回、核销。待审记录禁止登记人自审。
- 状态为 `draft → pending → posted`；退回为 `pending → draft`，沿用原 ID，原因留痕。草稿可取消，已入账资金通过原冲销流程更正。
- 业务员创建的 `requires_submission=true`，财务不能越过尚未提交的草稿直接入账。既有财务自建草稿继续支持直接确认。
- 草稿和待审款不计入已到账资金、会计余额或可核销余额。客户付款/退款可以先登记并提交，即使尚未确认应退金额；财务入账时仍校验可退余额。

## 路由

前缀 `/api/finance/v2`，JWT 仍用 `x-token`；分页、金额字符串、版本号、幂等键和错误格式沿用 v1.20。

| 路由 | 方法 | 用途 |
| --- | --- | --- |
| `/payments` | GET / POST | 登记或查询；业务员自动限定本人客户款 |
| `/payments/:id` | GET / PATCH | 明细 / 编辑可写草稿 |
| `/payments/:id/submit` | POST | `{version,idempotency_key}` 提交财务确认 |
| `/payments/:id/return` | POST | 财务 `{version,reason,idempotency_key}` 退回同一记录 |
| `/payments/:id/post` | POST | 财务核实实际资金、账户和日期后确认入账 |
| `/payments/:id/cancel` | POST | 有权限的登记人取消草稿，原因必填 |
| `/payments/:id/history` | GET | 按单据权限查看完整历史 |
| `/payments/:id/pdf` | GET | 同权限打印；返回原有 base64 PDF 响应结构 |
| `/payment-options/customers` | GET | 业务登记用客户选项，只返回编号、名称 |
| `/payment-options/accounts` | GET | 启用的人民币账户，只返回账户身份、不向业务员返回余额 |
| `/payment-options/orders?customer_id=` | GET | 该客户全部未归档订单，包括空单与无报价单 |

订单选项复用订单列表字段，并固定按 `create_date DESC, uid DESC` 排序。支持 `q` 搜索订单号、收货人、渠道、国家/地址、品名、唛头与日期等业务字段，以及 `p/s` 服务端分页。响应保持 `{items,total,page,page_size}`；每行保留 `order_uid/order_number/customer_id/customer_name`，增加 `uid/order_id` 别名和 `transportation/receiver/receiver_phone/mail/country/province/city/address/en_name/cn_name/post_code/zip_code/tag_all/create_date/update_date/total_weight/cargo_count`。`order_date` 用创建时间展示，历史记录缺少 `create_date` 时回退原 `order_date`；无订单号时以 UID 展示。只返回所选客户的订单，不包含客户电话/微信、报价、成本或财务余额。

登记字段：`partner_type:customer`、`partner_id`、`direction:incoming|outgoing`、`account_id`、`payment_date`、`amount`，可选 `reference`、`memo`、`reference_order_uids:[]`、`idempotency_key`。金额大于零；参考订单不能跨客户。

响应新增 `reference_orders:[{order_uid,order_number,customer_id}]`、`reference_order_uids`、`requires_submission`、`submitted_at/submitted_by_id/submitted_by_name`、`reviewed_at/reviewed_by_id/reviewed_by_name/review_remark`。订单后来更名、归档或改重不会改变已登记资金及原备注快照。

PDF 明示状态、资金金额、账户、登记与审核信息；备注订单明确标注“不代表核销或结清”，待审凭证不证明财务已确认到账。

## 历史收款与关账

旧 `/api/receipts` 不再接受新建，但历史查看、PDF、审计及既有待审旧收款的审核/驳回仍保留。旧收款不会复制成新的已入账 `FinancePayment`，避免与资金期初或净余额接入重复计账。

关账检查的 `payments` 项同时包含 `draft`、`pending`，返回 `draft_count` 和 `pending_count`；待审款不能被关账遗漏。幂等重放也重新校验当前单据权限，角色降低后不能借旧幂等键读取已失去权限的单据。

数据库迁移：`249fa0b1c2d3`，前序 `138e9f0a1b2c`。仅增量添加备注快照、提交/审核字段及登记人状态索引，不搬运或改写历史金额。
