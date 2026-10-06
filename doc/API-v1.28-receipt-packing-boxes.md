# API v1.28：收付款备注装箱单箱子

客户收付款继续使用统一财务接口 `/api/finance/v2/payments`，历史 `/api/receipts` 保持只读。业务员可以在尚未建立订单时登记收款，并选择同一客户或未绑定客户、来自多个装箱单的具体箱子。资金金额、财务确认流程、会计凭证和订单核销规则沿用现有逻辑。

## 创建、编辑与查询

`POST /payments`、`PATCH /payments/{id}` 新增可选字段：

```json
{
  "reference_box_uids": ["packing-box-1", "packing-box-2"]
}
```

- 最多 500 箱，编号须为非空字符串且不可重复；仅客户收付款支持。
- 新选箱子与装箱单必须存在、未归档，装箱单须属于收付款所选客户或尚未绑定客户（`customer_id: null`）；明确绑定其他客户的装箱单仍不可选择。无需箱子已有 `target_order_uid`。
- 备注未绑定客户的装箱单不会修改装箱单客户，也不会生成应收或核销资金。收付款客户仍为实际付款客户；快照保留装箱单原来的空客户编号，后续核销仍检查箱子当前所属订单的客户。
- 编辑省略字段时保留已选箱子，传 `[]` 清空。只能编辑草稿，仍校验 `version`。
- 保存箱子 UID、装箱单 UID、装箱单唛头、箱号、原单号、品名、重量、客户及登记时订单归属快照；之后修改箱子、装箱单或订单不会改写原收款事实或既存备注快照。
- 草稿新增其他箱子时保留既存箱子快照；既存箱子归档不阻止保留或移除该备注。

列表及详情返回以下新增字段：

```json
{
  "reference_box_uids": ["packing-box-1", "packing-box-2"],
  "reference_packing_boxes": [
    {
      "box_uid": "packing-box-1",
      "packing_list_uid": "packing-a",
      "list_number": "MARK-A",
      "box_number": 1,
      "transfer_id": "XD123456L",
      "item_name": "服装",
      "weight": 5.0,
      "customer_id": 1,
      "target_order_uid": null
    }
  ],
  "packing_order_uids": ["order-one"],
  "packing_order_references": [
    {"order_uid": "order-one", "order_number": "ORDER-1", "customer_id": 1, "box_uids": ["packing-box-1"]}
  ],
  "unresolved_packing_boxes": [
    {"box_uid": "packing-box-2", "list_number": "MARK-A", "box_number": 2, "reason": "箱子尚未分配订单"}
  ]
}
```

`reference_packing_boxes` 是登记时描述快照；`packing_order_*` 根据备注箱子当前的 `target_order_uid` 实时解析、按订单去重。未分配订单、箱子删除或归档、订单删除或归档、订单客户与收付款客户不一致时，返回 `unresolved_packing_boxes`，不计入可办理的关联订单。同一订单的多个备注箱子只产生一个订单候选，读取不会生成账单或分配收款金额。

## 箱子选择器

`GET /payment-options/packing-boxes?customer_id=1&q=MARK&p=1&s=10`

权限与现有收付款选项一致：业务员、财务、管理员。返回该客户及尚未绑定客户（`customer_id: null`）的未归档装箱单与箱子，支持装箱单唛头、原单号、品名及箱子 UID 搜索。前端标记“未绑定客户”，提示后续按箱子所属订单客户办理核销。可选 `packing_list_uid` 精确筛选装箱单。按装箱单创建时间倒序，再按箱号正序分页，返回 `{items,total,page,page_size}`，单页最多 200 箱。

## 按关联订单核销

`GET /order-settlements?payment_id=8&partner_id=1&p=1&s=20`

财务或管理员可通过 `payment_id` 限定为该客户收付款备注箱子的当前所属订单。响应同时包含 `packing_order_references`、`packing_order_uids`、`unresolved_packing_boxes`。同一订单只出现一次；报价、未结金额和阻断原因仍使用现有订单应收计算。

`POST /order-allocations` 可额外传 `packing_only: true`。服务端检查本次每个订单仍属于备注箱子的当前有效关联订单，否则返回 409，提示刷新箱子归属。继续校验收付款版本、订单报价快照、客户、剩余资金、当前订单余额和会计期间，在原事务内生成或调整订单应收账单并执行金额核销。

财务界面在收据备注箱子时默认显示这些箱子所属订单，也可切换到此客户全部订单。核销金额必须由财务确认，支持部分核销；未分配或不能核销的箱子可以留待后续处理，未分配资金继续保留。不会按箱子重量自动拆分金额，也不会因为同时备注多个箱子或订单而重复入账。

## PDF 与迁移

`GET /payments/{id}/pdf` 新增备注装箱单箱子表格，打印保存的装箱单唛头、箱号、原单号、品名和重量，跨页重复表头；保持原金额、状态、登记人、账户、财务意见及备注信息。

Alembic `57c2d3e4f5a6`（前序 `46b1c2d3e4f5`）为 `finance_payments` 增加可空文本字段 `reference_packing_boxes_json`（MySQL 使用 LONGTEXT，支持 500 箱长描述快照）。旧记录读取为空列表，不改变已存在的金额、状态或核销关系。
