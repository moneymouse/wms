# API v1.5：收据结清状态与结清差额

## 创建和读取收据

`POST /api/receipts` 新增可选表头字段 `settlement_status`，统一应用于本张收据的所有订单：

```json
{
  "customer_id": 1,
  "receipt_date": "2026-09-09",
  "payment_method": "bank_transfer",
  "settlement_status": "settled",
  "remark": "按实际到账登记，其余差额结清",
  "items": [{ "order_uid": "ORDER-UID", "amount": 950 }]
}
```

- `settled`：审核通过后停止追收关联订单的剩余应收。
- `unsettled`：不豁免余额，已足额收款的订单仍正常结清。
- 不传字段时，服务端将每笔订单的 `应收 − 已审核实收 − 本次收款` 按分计算后求和，合计小于 `30.00` 默认 `settled`，否则默认 `unsettled`。其他待审核收款不参与此默认值计算。
- 显式传入的值必须是上述两个字符串，其他值（包括 `null`）返回 `400`。业务员可覆盖默认值；结清差额没有30元上限。

金额必须大于0且不超过可收余额；**可收额度校验仍扣除其他待审核占用**。结清选择不修改报价、收据明细 `amount` 或收据 `total_amount`。

`GET /api/receipts`、`GET /api/receipts/<id>`、创建和审核响应均返回 `settlement_status`。历史收据返回 `null`，不追溯应用30元默认规则。原 `status` 继续表示审核状态：`pending`、`approved`、`rejected`。

详情的 `items[]` 新增：

| 字段 | 含义 |
| --- | --- |
| `settlement_difference` | 已审核固化的结清差额；新收据批准为 `unsettled` 时为0；历史、待审核、已驳回记录为 `null` |
| `preview_settlement_difference` | 仅待审核且 `settled` 的收据返回预计差额，其他情况为 `null` |

预计差额为 `max(应收快照 − 其他已审核实收 − 本次收款, 0)`，随其他收据的审核结果变化。批准时在同一事务中重新计算并保存最终差额，之后固定展示该值。现有 `remaining_after` 保持原有“创建时扣除其他待审占用后的可收余额快照”含义，不作为结清差额。

## 可收订单与审核

`GET /api/receivables/orders` 在分页和统计之前排除存在待审核或已批准 `settled` 收据的订单，创建接口同样校验，避免继续收取已申请结清的差额。结清收据驳回后解除限制。

`PUT /api/finance/receipts/<id>/review` 的请求不变。批准 `settled` 收据前，所有关联订单的其他待审核收据必须先批准或驳回；否则返回 `400`，提示相关订单和待处理收据号，整张保持待审核。已存在的其他收据仍可正常处理，不受待审核结清收据阻挡。

只有财务审核通过后才停止追收、计入实收及结清差额。创建人与审核人的权限约束不变，不能修改已提交收据；错误收据仍按驳回后复制新建处理。

## 财务应收台账

`GET /api/finance/accounts-receivable` 的 `data.items[]` 和 `data.totals` 新增数字字段 `settlement_difference`。统计只采用 `date_to` 截止时间之前已批准的实际收款和结清差额，历史空差额按0处理。

例如应收1000、实收950并结清，返回应收1000、实收950、结清差额50、未收0，状态 `paid`。`settlement_status` 筛选仍使用原值 `paid/partial/unpaid`，不与收据表头的 `settled/unsettled` 混用。收入汇总只包含实收，不包含结清差额。

## 迁移和发布

使用Alembic追加收据表头的可空结清状态和明细的可空结清差额，不回填历史记录。先执行迁移，再发布后端，最后发布前端。升级前的待审核收据仍沿用历史数值规则，批准时不自动豁免余额。

建议验收：29.99/30.00阈值、多单合计、人工覆盖、待审占额、驳回恢复、其他待审阻止结清批准、历史截止查询、实际收入与结清差额分离。
