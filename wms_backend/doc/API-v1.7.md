# API v1.7：财务锁、出库业务锁与重报价差价单

## 1. 两类锁定状态

订单锁拆分为彼此独立的两部分：

- `financial_lock`：订单出现任意收款单明细后永久生效。订单/货物/箱子重量、客户归属及箱子成员关系不可再修改，管理员修订也不能绕过。
- `business_lock`：订单至少有一个有效装箱单箱子，并且所有有效箱子均满足 `status=1` 且 `waybill_id` 非空时生效。

最后一个待出库箱填写转单号时，本次写入先正常完成出库和成本快照；事务完成后订单自然进入业务锁定。

`GET /api/orders/<uid>` 新增：

```json
{
  "financial_lock": {
    "active": true,
    "has_history": true
  },
  "business_lock": {
    "status": "none|locked|revision_open",
    "fully_outbound": true,
    "financial_locked": true,
    "unlock_eligible": true,
    "revision": null
  },
  "edit_policy": {
    "transportation": false,
    "financial_locked": true,
    "fully_outbound": true
  }
}
```

兼容字段 `receipt_locked`、`receipt_lock` 及原解锁/重锁 URL 暂时保留，但表达的是业务锁状态。

## 2. 编辑矩阵

业务锁控制订单详情中的运输方式，以及箱子/货物的原单号和转单号。普通业务内容、报价以及归档/删除不因全出库锁定而改变；管理员或订单负责人业务员开启修订后，运输方式和两个单号恢复原角色权限。重新锁定仍仅限管理员。财务锁仍独立保护重量、客户归属和箱子成员关系。

`clerk` 属于 `box_editor`：在未锁定或已开启修订时可编辑箱子内容、原单号、转单号和操作员；箱子称重仍沿用 `box_weight` 权限，不因本规则开放。

| 状态 | 重量/客户/箱子成员 | 普通业务内容 | 运输方式 | 原单号、转单号 | 报价 |
| --- | --- | --- | --- | --- | --- |
| 未全出库、无收据 | 重量按单包裹状态；其余原角色权限 | 原角色权限 | 原角色权限 | 原角色权限 | 原规则 |
| 未全出库、有收据 | 永久禁止 | 原角色权限 | 原角色权限 | 原角色权限 | 允许重报价 |
| 全出库、已锁定、无收据 | 已出库包裹重量禁止；其余原角色权限 | 原角色权限 | 禁止 | 禁止 | 原规则 |
| 全出库、已锁定、有收据 | 永久禁止 | 原角色权限 | 禁止 | 禁止 | 允许重报价 |
| 有权用户开启修订 | 重量继续按单包裹状态及财务锁判断 | 原角色权限 | 恢复原角色权限 | 原角色权限 | 原规则 |

已出库箱不能直接把 `waybill_id` 清空；撤销出库仍走专用接口，并受财务锁保护。

包裹级重量锁独立于上述两类订单锁：手动创建的包裹和从装箱单分配的箱子只要 `status` 已进入出库（`1`）或任一后续物流状态，`weight` 就不可修改。待出库（`0`）包裹仍按原角色权限称重；箱子经专用撤销出库接口回到 `0` 后可重新称重。首次登记转单号时可在同一请求中提交最终重量，成功后货物状态转为出库。后续通过 `PUT /api/cargo/<uid>`、`POST /api/cargo/<uid>/input`、`PUT /api/box/<uid>` 或 `PUT /api/box/<uid>/weigh` 修改重量均返回 `409`：

```json
{
  "code": 409,
  "msg": "货物已出库，重量不可修改；如需调整重量，请使用新的原单号创建包裹"
}
```

`status` 与出库日期 `date` 是服务端维护字段，通用货物更新接口拒绝客户端直接修改，避免先回退状态再绕过重量锁。

订单归档不受业务锁或财务锁影响。硬删除不受业务锁影响，但订单仍被报价、成本或收款等不可变快照引用时，继续返回 `409`，避免破坏历史引用。

归档订单采用单事务级联软归档：订单下所有货物/箱子，以及关联的成本记录、报价版本、重报价差价单和收款明细都会设置 `archive=true`；开放中的订单修订窗口同时自动关闭。归档数据不再进入活跃报价审核、应收台账、差价单或奖金统计，但收款单、订单版本和其他审计快照继续保留。

普通收款单不再自动关闭订单修订窗口。管理员完成核对后使用原重锁接口手动结束修订。

## 3. 重报价差价单

订单已有收据历史且新报价真正生效时，系统比较新旧两份有效报价的应收总额：

`delta_amount = new_receivable - old_receivable`

- 正数：`direction=collect`，待补收。
- 负数：`direction=refund`，待退款。
- 零：不生成差价单。
- 低价待审报价仅在管理员批准后生成；驳回或仍待审时不生成。
- 每个 `new_quote_id` 最多一条差价单，保证重试幂等。

差价单只是待处理的应收/应退任务，不是现金收据，不计入已收或已退金额。

### 查询待处理差价

- `GET /api/receivable-adjustments?status=pending&q=&p=1&s=20`
- 权限：`admin`、`finance` 查看全部；`salesperson` 仅查看自己负责报价的订单。

```json
{
  "code": 200,
  "data": [{
    "id": 1,
    "order_uid": "ORDER-UID",
    "order_id": "ORDER-001",
    "customer_name": "客户甲",
    "previous_quote_id": 10,
    "new_quote_id": 12,
    "old_receivable": 100.00,
    "new_receivable": 85.00,
    "delta_amount": -15.00,
    "direction": "refund",
    "status": "pending",
    "quoter_name": "业务员甲",
    "create_date": "2026-09-17 10:00:00"
  }],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

应收台账新增 `signed_balance` 和 `refund_due`；降价导致客户多付时不再把负余额静默截断。

## 4. 数据库迁移

`20260917_ac1d2e3f4a5b_price_adjustments.py` 新增 `order_price_adjustments`，并增加全出库状态查询所需的 cargos 复合索引。
