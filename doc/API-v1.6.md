# API v1.6：订单增量版本库与全锁单修订

## 1. 版本库规则

订单历史以不可变的 `order_uid` 为主键，采用追加式增量记录：

- 上线时，所有数据库中仍存在的订单（包括已归档订单）生成 `V1 baseline_import`。
- 新订单在创建事务内生成 `V1 order_created`。
- 此后一次成功且产生实际业务变化的用户操作生成一个新版本；纯 `update_date` 变化或无变化请求不生成版本。
- 更新只保存实际变化字段；新增保存完整 `after_data`；删除或解绑保存完整 `before_data`。
- `item_details` 没有稳定明细 ID，因此始终作为完整列表记录前后值，不逐行猜测匹配。
- 批量操作为每个受影响订单分别生成一个版本，并共享同一个 `correlation_id`。
- 第一期历史只读，不提供恢复旧版本、删除版本或修改版本的 API。

版本覆盖订单业务字段、业务员和客户基线，以及关联普通货物和箱子的品名、箱内明细、件数、重量、价格、唛头、两个单号、状态、出库日期、归档状态和操作员。未分配箱首次关联订单时，以完整箱内容进入该订单版本；解绑后的后续修改不再进入原订单历史。

报价、收款、奖金、成本快照、未分配箱的独立生命周期、17Track 实时查询结果和纯 `update_date` 变化不写入订单版本；它们继续使用现有专用历史、快照或审计记录。若报价采纳同时改变订单的 `transportation` 业务字段，仅该字段差异进入订单版本，报价内容本身仍不重复保存。

所有版本写入与对应业务修改位于同一数据库事务。任一步失败时，业务修改和版本记录一起回滚。

## 2. 权限与通用分页

以下三个历史接口只允许 `admin` 和 `store_manager`：

- `GET /api/orders/<uid>/versions`
- `GET /api/orders/<uid>/versions/<version_no>`
- `GET /api/order-history`

无有效 Token 返回 `401`，角色不匹配返回 `403`。分页参数统一如下：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `p` | `1` | 从 1 开始的页码 |
| `s` | `20` | 每页条数，服务端限制在 1 到 100 |

### 管理页：未重新锁定订单

`GET /api/admin/order-revisions/open?q=&p=1&s=10`

仅 `admin` 可访问。接口以 `order_receipt_revisions.status = open` 为当前状态真值，返回已经解锁但尚未手动重锁、也未因新收款单自动关窗的订单。结果按解锁时间正序排列，让最久未关闭的修订优先显示；`q` 可匹配订单 UID、订单号、客户、业务员、解锁人或解锁原因。

响应 `data` 包含 `items、total、page、page_size`；每项包含 `revision_id、order_uid、order_id、customer_name、salesman_name、opened_by_name、opened_at、reason、current_version`。管理页只提供进入订单详情的操作，重新锁定仍须在订单详情确认后执行。

## 3. 订单版本列表

`GET /api/orders/<uid>/versions?p=1&s=20`

版本按 `version_no` 倒序返回。`change_summary` 只描述本版涉及的实体、操作和字段，不包含完整前后值。

```json
{
  "code": 200,
  "data": {
    "items": [
      {
        "id": 12,
        "order_uid": "ORDER-UID",
        "version_no": 3,
        "action": "box_updated",
        "summary": "修改箱子内容和操作员",
        "operator_id": 7,
        "operator_name": "张三",
        "operator_roles": ["store_manager"],
        "reason": null,
        "correlation_id": "4ba9b14e9b6242ef9d2ebf29e210931c",
        "created_at": "2026-09-16 10:30:00",
        "order_id": "ERP-001",
        "customer_name": "客户A",
        "deleted": false,
        "change_count": 1,
        "change_summary": [
          {
            "sequence_no": 1,
            "entity_type": "box",
            "entity_uid": "BOX-UID",
            "operation": "update",
            "fields": ["item_details", "workers"]
          }
        ]
      }
    ],
    "total": 3,
    "page": 1,
    "page_size": 20
  }
}
```

订单当前已被硬删除时，仍可通过已知 `order_uid` 读取该列表。订单从未建立版本时返回空列表；不存在的具体版本由详情接口返回 `404`。

## 4. 版本详情与完整快照

`GET /api/orders/<uid>/versions/<version_no>`

响应同时包含该版增量 `changes` 和从 V1 顺序应用至目标版本后得到的 `snapshot`。

```json
{
  "code": 200,
  "data": {
    "order_uid": "ORDER-UID",
    "version_no": 3,
    "action": "box_updated",
    "summary": "修改箱子内容和操作员",
    "operator_id": 7,
    "operator_name": "张三",
    "operator_roles": ["store_manager"],
    "reason": null,
    "correlation_id": "4ba9b14e9b6242ef9d2ebf29e210931c",
    "created_at": "2026-09-16 10:30:00",
    "order_id": "ERP-001",
    "customer_name": "客户A",
    "deleted": false,
    "changes": [
      {
        "sequence_no": 1,
        "entity_type": "box",
        "entity_uid": "BOX-UID",
        "operation": "update",
        "fields": ["item_details", "workers"],
        "before_data": {
          "item_details": [
            {"item_name": "SHOES", "customs_code": "6404", "piece_count": 2}
          ],
          "workers": [{"worker_id": 3, "worker_name": "李四"}]
        },
        "after_data": {
          "item_details": [
            {"item_name": "SHOES", "customs_code": "6404", "piece_count": 3}
          ],
          "workers": [{"worker_id": 5, "worker_name": "王五"}]
        }
      }
    ],
    "snapshot": {
      "order": {
        "uid": "ORDER-UID",
        "order_id": "ERP-001",
        "customer_name": "客户A",
        "salesman": {"id": 8, "name": "业务员A"},
        "customers": [{"id": 2, "name": "客户A"}],
        "revision_status": "open",
        "revision_reason": "更正箱内明细"
      },
      "cargos": [],
      "boxes": [
        {
          "uid": "BOX-UID",
          "transfer_id": "ORIGINAL-001",
          "waybill_id": "TRACK-002",
          "item_details": [
            {"item_name": "SHOES", "customs_code": "6404", "piece_count": 3}
          ],
          "workers": [{"worker_id": 5, "worker_name": "王五"}]
        }
      ],
      "deleted": false
    }
  }
}
```

`entity_type` 为 `order`、`cargo` 或 `box`；`operation` 为 `create`、`update` 或 `delete`。删除订单版本的 `snapshot.deleted` 为 `true`，并额外返回 `last_existing_snapshot`，用于展示删除前最后一份完整订单。

## 5. 已删除订单历史

`GET /api/order-history?deleted_only=1&q=&p=1&s=20`

该接口返回每个订单的最新版本，用于已删除订单入口。`deleted_only` 默认是 `1`，此时只返回最新版本为删除墓碑的订单；传 `0`、`false` 或 `no` 时返回所有订单的最新历史元数据。`q` 仅匹配订单 UID、版本中保存的订单号或客户名称。

```json
{
  "code": 200,
  "data": {
    "items": [
      {
        "order_uid": "DELETED-ORDER-UID",
        "version_no": 8,
        "action": "order_deleted",
        "summary": "删除订单",
        "order_id": "ERP-009",
        "customer_name": "客户B",
        "deleted": true,
        "created_at": "2026-09-16 12:00:00",
        "operator_name": "管理员"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  }
}
```

历史中的旧 `transfer_id` 或 `waybill_id` 不进入订单列表或删除历史的全局搜索；只有打开已知订单的版本详情后才能查看旧值。

## 6. 订单详情、锁定状态与编辑策略

`GET /api/orders/<uid>` 保留原订单数据和兼容字段 `receipt_locked`，并新增：

```json
{
  "current_version": 3,
  "receipt_lock": {
    "status": "none|locked|revision_open",
    "has_history": true,
    "unlock_eligible": false,
    "blockers": [],
    "warnings": ["approved_receipt"],
    "revision": {
      "id": 6,
      "reason": "更正箱内明细",
      "opened_by_id": 1,
      "opened_by_name": "管理员",
      "opened_at": "2026-09-16 10:00:00"
    }
  },
  "lock_warnings": [
    {
      "code": "approved_receipt",
      "message": "订单存在已审核收款单；修订不会改写原收款快照"
    }
  ],
  "edit_policy": {
    "order_fields": true,
    "order_weight": false,
    "salesman": true,
    "customer_assignment": false,
    "cargo_content": true,
    "cargo_weight": false,
    "box_content": true,
    "box_weight": false,
    "tracking_numbers": true,
    "box_workers": true,
    "box_membership": false,
    "archive_or_delete": false,
    "lock_status": "revision_open",
    "has_receipt_history": true,
    "revision_open": true
  }
}
```

`edit_policy` 已结合锁定状态和当前角色计算，前端不得自行推断权限。`lock_warnings` 的代码可为 `pending_receipt`、`approved_receipt`、`bonus_assigned`；它们用于风险确认，不再阻止有权用户开启修订。

### 6.1 锁定矩阵

| 操作 | 无收据历史 | 已锁定 | 修订中 |
| --- | --- | --- | --- |
| 订单非重量字段 | 沿用角色权限 | 禁止 | 沿用角色权限 |
| 业务员 | 沿用原权限 | 禁止 | 沿用原权限 |
| 客户归属 | 沿用原权限 | 禁止 | 禁止 |
| 订单或货物/箱子重量 | 沿用原权限 | 禁止 | 永久禁止 |
| 普通货物/箱子非重量内容 | 沿用角色权限 | 禁止 | 沿用角色权限 |
| `transfer_id`、`waybill_id` | 沿用角色权限 | 禁止 | 沿用角色权限 |
| 箱子操作员 | 沿用角色权限 | 禁止 | 沿用角色权限 |
| 新增、移除、分配或解绑箱子 | 沿用角色权限 | 禁止 | 禁止 |
| 归档或删除订单/关联箱子 | 沿用角色权限 | 禁止 | 禁止 |

违反锁定策略返回 HTTP `409`，业务数据和版本数据均不改变，也不生成空版本。
即使订单没有收据历史，只要目标仍被报价、成本或收款等不可变快照引用，硬删除订单、箱子、装箱单或客户也返回 `409`；可先使用归档，系统不会为完成硬删除而改写或清除财务快照。

### 6.2 开启和结束修订

- `POST /api/orders/<uid>/receipt-unlock`：`admin` 可操作任意订单；`salesperson` 仅可操作本人负责的订单。请求体 `{ "reason": "必填，最多 512 个字符" }`。
- `POST /api/orders/<uid>/receipt-relock`：仅 `admin`，请求体 `{ "remark": "可选，最多 512 个字符" }`。

任何锁定订单均可由管理员开启修订，订单负责人业务员也可开启本人订单的修订。待审核收款、已审核收款和已分配奖金只显示风险警告。修订期间沿用原角色权限；重新锁定仍由管理员完成。

开启修订和重新锁定本身各生成一个订单版本。报价继续走独立报价版本流程；收款、成本和奖金快照不可修改。创建新收款单会按原流程关闭开放的修订窗口，并为每个被自动关闭的订单生成关联版本。

## 7. 箱内容与操作员原子保存

`PUT /api/box/<uid>` 新增可选 `worker_ids`，用于在一次事务内保存箱内容和操作员：

```json
{
  "item_details": [
    {"item_name": "SHOES", "customs_code": "6404", "piece_count": 3}
  ],
  "remark": "重新核对",
  "transfer_id": "ORIGINAL-001",
  "waybill_id": "TRACK-002",
  "worker_ids": [3, 5]
}
```

`worker_ids` 必须是数组，最多 4 个正整数；传空数组表示清空操作员。请求成功时箱内容、操作员和订单版本一起提交，只生成一个订单版本；任一步失败则全部回滚。未传 `worker_ids` 时保留原操作员。

原有 `PUT /api/box/<uid>/workers` 和 `POST /api/box/<uid>/workers/add` 保留兼容，也遵守相同锁定策略并写入订单版本。

## 8. 两个单号的统一语义

- `transfer_id`：原单号。
- `waybill_id`：转单号（运单号），变更成功后按现有流程注册新运单。

已出库箱在修订中允许修改这两个单号。当前箱记录更新，但原成本、收款和奖金快照不改写；旧单号只通过订单版本详情追踪。改单号不是恢复历史版本，也不得通过改单号重新计算旧快照。

## 9. 迁移和发布

本版本的 Alembic 迁移为：

`alembic/versions/20260916_8a9b0c1d2e3f_order_incremental_versions.py`

迁移的 `down_revision` 为 `7f8a9b0c1d2e`。生产发布必须在停止业务写入后依次执行：

1. 备份数据库并确认当前 Alembic revision。
2. 执行 `alembic upgrade head`，创建 `order_versions` 和 `order_version_changes`。
3. 执行 `python -m scripts.backfill_order_versions`，为所有现存及已归档订单生成 V1；可用 `--batch-size <正整数>` 控制遍历批次。脚本幂等，已存在 V1 的订单会跳过，失败后可在继续停写的前提下重跑。
4. 核对脚本输出的 `orders`、`baseline_imports`、`v1_coverage` 和 `verified`。`verified=True` 表示 `orders == v1_coverage`，即每个当前订单都已有任意来源的 V1；冻结写入的首次发布还必须确认 `orders == baseline_imports`，即所有上线前订单的 V1 均为 `baseline_import`。
5. 抽查普通订单、归档订单、含箱内明细和操作员的订单能重建 V1。
6. 发布后端和前端，最后恢复业务写入。

发布校验可使用：

```sql
SELECT COUNT(*) AS orders FROM orders;

SELECT COUNT(DISTINCT order_uid) AS baseline_imports
FROM order_versions v
JOIN orders o ON o.uid = v.order_uid
WHERE v.version_no = 1 AND v.action = 'baseline_import';

SELECT COUNT(DISTINCT order_uid) AS v1_coverage
FROM order_versions v
JOIN orders o ON o.uid = v.order_uid
WHERE v.version_no = 1;
```

脚本字段含义如下：

| 字段 | 含义 |
| --- | --- |
| `orders` | 当前 `orders` 表中的订单总数，包含已归档订单 |
| `baseline_imports` | `version_no=1 AND action=baseline_import` 的订单数 |
| `v1_coverage` | 已存在任意 V1 的订单数，包括 `baseline_import` 和 `order_created` |
| `verified` | 是否满足 `orders == v1_coverage` |

开放写入前应满足 `verified=True`，并在首次冻结发布中满足 `orders == baseline_imports == v1_coverage`。写路径保留缺少基线时在同一事务内先补 V1 的安全兜底，但该兜底不能替代正式发布回填。

版本历史长期保留。当前订单、货物或用户被硬删除时，历史不级联清除；系统没有普通 UI/API 用于删除版本。上线前已经硬删除的数据无法补录，本次发布也不尝试从旧操作日志推断或回放历史。
