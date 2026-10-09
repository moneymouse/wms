# API v1.38：原单号—转单号表支持部分成功

`POST /api/order/upload/transfer_table` 按业务订单分别保存。一个订单的上传记录失败后，其他订单继续保存，报告只列未成功的记录及各自原因。无需数据库迁移。

## 保存规则

- 同一订单的导入货物在一个事务中处理，单号、出库状态和时间、成本快照、出库事实、订单版本一起提交或回滚。未分配订单的货物各自处理。
- 客户归属不一致、重量无效、归档、归属变化及保存异常只影响所在订单，不撤销已成功提交的其他订单，也不中断后续订单。
- 客户校验等原有规则保留。同一原单号匹配多个货物时分别处理其所在订单，不任意选择一条。
- 原单号不存在、原单号为空、转单号为空均计入失败明细；不创建新货物。缺少文件、文件解析失败、非法参数或无操作权限仍在保存之前拒绝整次请求。
- 重传已经保存的相同转单号仍计为成功，不重复生成出库、成本和版本记录，也不重复注册追踪。
- 17Track 只接收成功提交且转单号发生变化的记录。追踪注册失败不会回滚已保存订单，也不加入保存失败清单。

## 响应

保留 `cargo_list`、`success_list`、`cargo_count`，新增 `success_items`、`failed_list`、`tracking_error`。

| 字段 | 含义 |
| --- | --- |
| `cargo_list` | 上传的原单号到转单号映射 |
| `success_list` | 所有成功记录的 `[货物UID, 转单号]`，包含无变化的重传 |
| `cargo_count` | 成功货物记录数，与 `success_list` 长度一致，并非业务订单数 |
| `success_items` | 成功记录的 UID、订单 UID、订单号、原单号、转单号 |
| `failed_list` | 未保存记录的相同定位字段，以及 `code`、`reason`；未匹配记录的 UID 和订单 UID 为 `null` |
| `tracking_error` | 无追踪错误时为 `null`；否则为 `{ "code": 502或500, "reason": "错误说明" }` |

部分成功示例（HTTP 200）：

```json
{
  "code": 207,
  "msg": "部分订单上传失败，其他订单已保存",
  "cargo_count": 1,
  "cargo_list": {"ORIG-OK": "WB-OK", "ORIG-BAD": "WB-BAD"},
  "success_list": [["cargo-ok", "WB-OK"]],
  "success_items": [
    {"uid": "cargo-ok", "order_uid": "order-ok", "order_id": "ORDER-OK", "transfer_id": "ORIG-OK", "waybill_id": "WB-OK"}
  ],
  "failed_list": [
    {"uid": "cargo-bad", "order_uid": "order-bad", "order_id": "ORDER-BAD", "transfer_id": "ORIG-BAD", "waybill_id": "WB-BAD", "code": 400, "reason": "出库前货物重量必须大于0"}
  ],
  "tracking_error": null
}
```

全成功为 HTTP 200、`code=200`；全部保存失败为 HTTP 400、`code=400`。失败项保留各自的状态码，如 `400` 校验失败、`403` 权限不足、`404` 记录不存在、`409` 并发冲突、`500` 保存异常。

存在追踪错误时维持 HTTP 200、`code=502`（含原有 `rejected`）或 `code=500`，`success_items`、`failed_list` 仍描述真实保存结果。前端分别展示保存失败和追踪失败，不能根据响应整体状态或重复转单号推断每条记录的保存结果。
