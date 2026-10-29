# API v1.50 — 业务收付款的应收款列表

## GET `/api/receivables/unregistered-orders`

需登录，允许 `salesperson`、`admin`、`finance`。列表始终限定为当前用户的有效报价（`is_final=true`，状态为 `adopted` / `approved`），沿用业务收款的报价人归属口径，不按订单跟单人归属。管理员也只返回本人报价，传入 `owner_id` 不会扩大范围。

返回未归档、实时应收大于零、尚未登记有效收付款的订单。以下记录会排除关联订单，排除发生在统计总数和分页之前：

- 新收付款 `draft` / `pending` / `posted` 的备注订单，收款和付款均计入；已保存草稿和退回待修改记录保留在原收付款中处理，避免重复登记。`cancelled` / `reversed` 不计入。
- 备注箱子当前所属的、未归档且客户一致的订单；未分配、归档及跨客户箱子不计入。
- 已确认客户收付款的有效核销所对应的订单账单行；仅有备注不代表已经核销。
- 历史收款 `pending` / `approved` 的未归档关联项，包含部分收款；`rejected` 不计入。

搜索和筛选参数：

| 参数 | 说明 |
| --- | --- |
| `q` | 订单号或客户名称，模糊查询 |
| `customer_id` | 客户 ID，可选 |
| `order_uid` | 精确订单 UID，可选 |
| `date_from` / `date_to` | 订单创建日期，`YYYY-MM-DD`，包含起止日 |
| `p` / `s` | 页码及每页数量，默认 1 / 20，上限 100 |

响应沿用 `/receivables/orders`，实时应收按每箱计费重向上取整后合计，不使用过期报价重量快照。

```json
{
  "code": 200,
  "data": [{
    "uid": "order-uid", "order_id": "ORD-001", "create_date": "2026-10-29 09:00:00",
    "customer_id": 1, "customer_name": "客户", "quoter_id": 3, "quoter_name": "业务员",
    "effective_date": "2026-10-29 10:00:00", "weight_snapshot": 10.5, "billing_weight": 11,
    "receivable_amount": 132, "approved_received": 0, "pending_amount": 0,
    "settlement_difference": 0, "available_amount": 132
  }],
  "total": 1, "page": 1, "page_size": 20
}
```

非法日期、起止日期颠倒或不存在的客户返回 400；无角色权限返回 403。此接口仅读取数据，不创建账单、收付款或核销，不改变财务余额。
