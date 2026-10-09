# API v1.33：供应商订单级对账

日期：2026-10-06。扩展 [供应商统一对账 API v1.31](API-v1.31-supplier-reconciliation.md)，保持原有上传模板、路径、权限和应付草稿流程。

## 匹配与重量

模板「原单号」列可填写供应商提供的订单号。先精确匹配 `Cargo.transfer_id`；只有没有任何包裹候选时才精确匹配 `Order.order_id`，不匹配内部订单 UID。候选包裹重复、归档、无订单或重量不符时仍为包裹异常，不改用订单匹配。重复订单号（包括历史归档记录）不自动选择。

唯一未归档订单按其全部未归档包裹的 `Cargo.weight` 原始实重求和，包括普通包裹和装箱单箱子。`Order.total_weight`、计费重以及单包裹向上取整不参与比较。没有包裹、总重非正、任何重量缺失/为负/非有限值均为异常。比较使用原始 Decimal 之和，显示才保留 3 位小数。

| 对账层级 | 上传重量减系统实重 | 费用归属 | 转单号 |
| --- | --- | --- | --- |
| 包裹级 | `-0.5 ≤ 差值 ≤ 0` kg | 包裹所属订单，保留包裹 UID | 填写时必须等于该包裹系统转单号 |
| 订单级 | `-5 ≤ 差值 < 0` kg | 整笔费用归属订单，包裹 UID 留空 | 保留上传证据，不核对单包裹 |

订单总实重 30 kg 时，上传 25 kg、29.999 kg 可通过；24.999 kg、30 kg、30.001 kg 均异常。订单级上传重量必须严格小于系统总实重，0 kg 差值不通过。上传费用不拆分到某个包裹。

## 兼容响应

`POST /api/supplier-reconciliation/batches`、批次列表/详情、`POST /batches/:id/reconcile` 返回的明细新增：

```json
{
  "original_number": "ORDER-001",
  "match_type": "order",
  "system_weight_scope": "order_total",
  "cargo_uid": null,
  "order_uid": "order-uid",
  "order_number": "ORDER-001",
  "system_waybill": null,
  "system_weight": "30.000",
  "weight": "29.000",
  "weight_difference": "-1.000"
}
```

包裹级 `match_type="cargo"`、`system_weight_scope="cargo"`；未匹配行均为 `null`。重量异常但已唯一匹配的行仍显示层级和系统重量。

批次新增 `order_weight_difference_range:{min:"-5.000",max:"0.000",min_inclusive:true,max_inclusive:false}`；原有包裹级 `weight_difference_range` 和 `weight_tolerance` 保持不变。

`GET /orders/:order_uid/costs` 的 `items` 新增 `match_type`、`source_original_number`、`source_system_weight`，用于订单成本页面显示「整单对账」或「包裹对账」。手工账单来源字段为 `null`。费用仍按原有应付行 `order_uid` 汇总，草稿只计待确认金额，生效后计实际成本，供应商贷项按原订单冲减。

## 重复与生效复核

保留包裹级同供应商、包裹 UID、系统转单号的重复检查。整单费用按其未归档包裹发运集合（各包裹 UID、系统转单号）检查覆盖：和既有整单或逐包裹费用存在任何发运包裹交集均须复核，费用/上传重量改变不能绕过，货物移到其他订单也不能绕过。同文件重叠行返回 `overlapping_in_file`，双方不生成草稿；跨批次已有草稿或生效账单覆盖时返回 `previous_import_duplicate`。

新增一个包裹或仅更换一个包裹转单号时，若其余包裹的发运身份仍与旧费用相同，不能把它们再次自动计费。全部活跃包裹换成新的发运身份（新包裹或新转单号），与旧费用完全无交集时可以通过；该规则不按订单 UID 永久拦截。已取消草稿不参与重复检查。

订单匹配歧义返回 `ambiguous_order`。其余异常沿用 v1.31，包括 `archived_source`、`invalid_system_weight`、`weight_mismatch`、`original_not_found`。

财务过账同事务重新执行原单号优先、订单唯一性、重量范围及来源快照验证。订单号、包裹集合、每个包裹原始重量或系统转单号变化阻止旧草稿生效；总重相同但成员或重量明细变化同样阻止。新出现同号包裹或第二个同号订单也会阻止生效。异常行可通过版本化「重新核对异常」追加草稿；旧已通过行不会重复生成。整单应付不影响订单应收、财务过账权限、来源保护或贷项按订单限额。

本扩展复用现有可空 `cargo_uid` 和已有 `order_uid`、`match_snapshot_json`，无新增数据库迁移。
