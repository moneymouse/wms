# API v1.3：管理员订单收据修订窗口

## 兼容性变更

`GET /api/orders/<uid>` 保留原有 `receipt_locked`，并新增 `receipt_lock`：

```json
{
  "status": "none|locked|revision_open",
  "has_history": true,
  "unlock_eligible": true,
  "blockers": [],
  "revision": null
}
```

`blockers` 可取 `pending_receipt`、`approved_receipt`、`bonus_assigned`。旧客户端可继续只读取 `receipt_locked`。

## 新接口

### 解锁订单

- `POST /api/orders/<uid>/receipt-unlock`
- 权限：`admin`
- 请求：`{ "reason": "必填，最多 512 个字符" }`
- 成功：`200`，`data` 为更新后的完整 `receipt_lock`

仅当订单关联的所有收款单均为 `rejected`，且没有已分配奖金的包裹时允许解锁；已有出库包裹不影响解锁。业务状态冲突返回 `409`。

### 重新锁定订单

- `POST /api/orders/<uid>/receipt-relock`
- 权限：`admin`
- 请求：`{ "remark": "可选，最多 512 个字符" }`
- 成功：`200`，`data.status` 为 `locked`

创建新收款单也会在同一事务内自动关闭其订单的开放修订窗口。原 `rejected` 收款单保持不可修改、不可删除，继续通过“复制新建”生成修正单。

## 错误码

- `400`：原因或说明字段无效
- `403`：非管理员调用解锁/重新锁定
- `404`：订单不存在
- `409`：订单状态、收款状态或奖金状态不允许本次操作
