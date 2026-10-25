# API v1.46 - 订单详情关联收付款记录

## GET /api/finance/v2/order-payments/{order_uid}

JWT 使用 `x-token`。权限为 `salesperson`、`finance`、`admin`，订单必须存在。订单详情现有读取权限不按业务员归属过滤；此接口延续该订单读取边界，并在服务层校验资金读取权限。业务员仅看到本人登记的客户非期初收付款，财务和管理员可查看全部客户资金。记录和汇总使用相同可见范围，`visibility` 返回 `own` 或 `all`，业务员汇总不能当作全单结算金额。

参数 `p`（从 1 开始，默认 1）、`s`（默认 30，最多 200）。记录按资金 ID 倒序分页，摘要始终汇总可见范围的全部关联记录，不随分页改变。

关联按精确身份识别，联合以下来源并按资金 ID 去重：

- `reference`：已保存的备注订单快照中 `order_uid` 精确匹配。
- `packing`：备注箱子当前属于该订单，箱子与订单未归档，订单当前关联客户与收付款客户一致；有明确客户关联时不使用客户名称替代。箱子后来移单会改变这类关联。
- `allocation`：该订单明确映射的受管应收账单或旧账接入账单已有资金核销，包括已撤销核销。普通多订单账单的行备注无法提供每单分摊金额，因此不用于推算订单核销。

不会按备注文字、订单号搜索或相似 UID 匹配。订单更名、客户变化、箱子移单或核销撤销均不会删除已明确关联的资金核销历史。

响应沿用 `{code:200,data:...}`，`data` 包含：

| 字段 | 含义 |
| --- | --- |
| order_uid / order_number | 订单身份与当前展示号 |
| visibility | `own` / `all` |
| items / total / page / page_size | 当前页与分页信息 |
| summary.received_amount | 可见资金在本单的有效收款核销 |
| summary.refunded_amount | 可见资金在本单的有效付款核销 |
| summary.net_received_amount | 收款核销减付款核销 |
| summary.related_received_amount / related_refunded_amount | 可见关联已入账收/付款流水的整笔金额，不能当作本单已收/已退金额 |
| summary.draft_count / pending_count | 可见关联草稿 / 待确认记录数 |

`items` 每行包含 `id`、`number`、`payment_date`、`direction`、`is_opening`、`amount`、`status`、`account_name`、`reference`、`memo`、`created_by_name`、`relation_types`、`order_allocated_amount`。`relation_types` 是 `reference/packing/allocation` 的数组。一笔资金备注或核销多个订单时，`amount` 仍是原整笔流水，`order_allocated_amount` 只包含本单有效分配。财务可见的 `is_opening=true` 记录须标注为期初余额；期初资金实际核销到本单的部分仍计入有效分配。

所有金额为两位小数字符串。生效统计只使用 `posted` 资金及 `active` 核销，排除纯贷项抵扣；草稿、待确认、已取消、已冲销及已撤销核销不增加本单生效金额。已取消/已冲销资金和已撤销核销关联仍可在记录中查看。

接口只读，不确认报价、不生成账单、不核销，也不计算报价或应收余额。`received_amount` 等新资金核销金额不包含旧 `PaymentReceipt` 历史现金或结算减免；旧收款继续通过既有历史收款入口查看，不能将包含减免的旧结算金额当作实收现金再次累加。
