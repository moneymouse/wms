# API v1.8：重报价差价补收

## 1. 差价列表与详情

- `GET /api/receivable-adjustments?status=pending&q=&p=1&s=20`
- `GET /api/receivable-adjustments/<id>`

管理员、财务可查看全部；业务员按订单当前有效报价的负责人查看。详情不存在或已归档时返回 `404`，超出业务员跟单范围时返回 `403`。详情可读取已处理差价，供驳回收款单复制时判断是否仍可补收。

列表与详情在原差价字段上增加：

| 字段 | 含义 |
| --- | --- |
| `customer_id` | 当前有效客户；未关联客户时为空 |
| `approved_received` | 关联该差价的审核通过实收金额 |
| `pending_amount` | 关联该差价的待审核金额 |
| `available_amount` | 当前可登记补收金额 |
| `collection_blocked_reason` | 无法补收原因；可登记时为空 |

```json
{
  "code": 200,
  "data": {
    "id": 3,
    "order_uid": "ORDER-UID",
    "order_id": "ORDER-001",
    "customer_id": 1,
    "customer_name": "客户甲",
    "old_receivable": 100,
    "new_receivable": 140,
    "delta_amount": 40,
    "direction": "collect",
    "status": "pending",
    "approved_received": 15,
    "pending_amount": 0,
    "available_amount": 25,
    "collection_blocked_reason": null
  }
}
```

可补收金额取以下两项的较小值，最低为零：

1. 本笔正差价减关联已审实收、关联待审金额。
2. 订单当前应收减全部已审实收、历史结清差额及全部待审金额。

同一差价已有待审补收单时，即使只登记了一部分，`available_amount` 也为零；需先审核或驳回再登记下一笔。存在待审结清收据、无有效客户、无有效报价、无创建权限、差价已处理或订单无可收余额时，返回零及相应原因。财务可以查看，但创建收款单仍限业务员、管理员。

## 2. 登记差价补收

沿用 `POST /api/receipts`，明细新增可选 `adjustment_id`：

```json
{
  "customer_id": 1,
  "receipt_date": "2026-09-30",
  "payment_method": "bank_transfer",
  "settlement_status": "unsettled",
  "remark": "分次补收重报价差价",
  "items": [{ "order_uid": "ORDER-UID", "amount": 10, "adjustment_id": 3 }]
}
```

- 差价补收单只包含一笔明细；未关联差价的普通收款单继续支持同客户多订单。
- 只允许关联同订单、未归档、`pending`、`direction=collect` 的差价。
- 金额必须大于零，且不超过差价当前可补收金额。
- 差价补收固定 `settlement_status=unsettled`；省略时服务端自动设置，显式传 `settled` 时拒绝。差价补收不应用“小于30元默认结清”，剩余未收差价不会自动减免；订单实际余额为零时应收台账仍显示已结清。
- 创建和审核均校验订单余额及差价余额，并使用订单行锁串行化同订单的写入。再次提交已有待审补收单的差价会被拒绝。
- 收款单明细响应返回 `adjustment_id`，普通及历史明细为空。

## 3. 审核、驳回与处理状态

沿用 `PUT /api/finance/receipts/<id>/review`。创建人不能审核本人收款单。

提交仅占用余额，不改变差价的 `pending` 状态或实收。审核通过后，关联实收达到差价金额时标记 `resolved`。同订单当前剩余应收已为零时，关闭该订单全部待处理正差价；普通收款通过审核补足或结清订单时也执行此规则，避免重报价互抵后留下不可补收的正差价任务。

部分补收通过审核后保留余款，可继续登记。驳回保留收款单及差价关联，释放待审占用；复制新建须重新获取差价详情，并以最新可补收金额限制本次金额。登记后再次重报价导致应收快照变化时，拒绝批准旧收款单，须驳回后重新登记。

`direction=refund` 的负差价继续作为财务处理任务展示，不允许关联正数收款，不因补收审核而关闭。本次不新增退款现金流水接口。

## 4. 数据库迁移

`20260930_ce3f4a5b6c7d_adjustment_receipt_items.py` 为 `payment_receipt_items` 新增 nullable 外键 `adjustment_id` 及索引，引用 `order_price_adjustments.id`。

发布后端前先执行 `alembic upgrade head`。历史收款明细保持 `adjustment_id=NULL`，不推断历史收款与差价之间的关联，不改写历史实收及结清快照。
