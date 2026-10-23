# WMS Backend API 接口文档

**Base URL:** `http://localhost:5001`

**版本:** 1.47

出货草稿搜索排除已出货装箱单，非订单业务员可只读查看报价版本及各版本报价说明，见 [API v1.47](API-v1.47-shipping-search-and-quote-visibility.md)。

拍照装箱单检查页支持每箱备注及批量修改备注，草稿保存与确认入库保留 `remark`，见 [API v1.43](API-v1.43-intake-box-remarks.md)。

纸单识别加入系统品名库和常见商品参考，检查、草稿与确认入库支持每箱多项品名及独立件数，见 [API v1.42](API-v1.42-intake-goods-recognition.md)。

财务“退回修改”自动通知收据原登记员工，并支持从收件箱直接打开对应收据详情，见 [API v1.41](API-v1.41-finance-return-messages.md)。

站内消息的发送、个人收件箱、未读数量和已读接口见 [API v1.40](API-v1.40-in-app-messages.md)。各业务服务可使用统一发送接口指定员工与处理路径；首期收件箱通过三分钟轮询同步消息。

纸单照片改存持久化文件目录；存储管理展示全部照片来源、磁盘占用和装箱单跳转，可直接预览并删除照片，未达到建议保留期限时提示确认，详见 [API v1.36](API-v1.36-photo-storage-management.md)。

纸单识别与确认复用手动创建的唛头重名规则，自动追加日期和序号，见 [API v1.39](API-v1.39-intake-mark-deduplication.md)。

财务账簿与审计新增接口见 [API v1.20 财务](API-v1.20-finance.md)。原订单接口保持兼容。

统一客户收付款见 [API v1.22](API-v1.22-customer-payments.md)，订单应收与财务核销见 [API v1.23](API-v1.23-order-settlement.md)，出库后移除限制与撤销出库见 [API v1.21](API-v1.21-outbound-removal.md)。旧 `POST /api/receipts` 已返回410；既有收款的查询、打印、历史和待审核清理保留。

客户管理与订单客户联系方式权限见 [API v1.23](API-v1.23-customer-permissions.md)。

订单号与原单号随机生成见 [API v1.25](API-v1.25-auto-numbers.md)，撤销出库后恢复原单号编辑与生成见 [API v1.26](API-v1.26-original-number-editing.md)。

装箱单出货确认单与服务器草稿见 [API v1.27](API-v1.27-packing-shipping-drafts.md)，收据备注箱子和按所属订单核销见 [API v1.28](API-v1.28-receipt-packing-boxes.md)，装箱单批量生成原单号见 [API v1.29](API-v1.29-packing-original-numbers.md)。随机订单号与原单号统一为 `D8xxxxxxxxL`，出货确认单改为每行一单并增大字号，见 [API v1.32](API-v1.32-shipping-layout-and-number-format.md)。

纸质单改为上传者检查后完成上传，待核对页面移除，出货确认单草稿改为独立页面，见 [API v1.30](API-v1.30-uploader-check-and-shipping-drafts-page.md)。

统一 Excel 供应商对账、异常重核、自动生成应付草稿及订单实际成本见 [API v1.31](API-v1.31-supplier-reconciliation.md)。

原单号未匹配货物时支持精确匹配订单号并按订单总实重对账，订单级上传重量须小于实重且最多少 5 kg，见 [API v1.33](API-v1.33-order-level-supplier-reconciliation.md)。

装箱单上传检查采用每箱独立 `worker_ids`，旧整单人员仅兼容填入尚未配置人员的箱子，见 [API v1.34](API-v1.34-intake-per-box-workers.md)。有上传照片或纸单来源的装箱单允许删除，并清理对应上传照片，仍保留原有权限、出库和成本历史保护，见 [API v1.35](API-v1.35-packing-photo-deletion.md)。

---

## 通用说明

### 认证方式

除特殊标注外，所有接口均需要在请求头中携带 JWT Token：

```
x-token: <JWT_TOKEN>
```

### 响应格式

所有接口返回 JSON 格式，基本结构：

```json
{
  "code": 200,
  "msg": "success",
  "data": {}
}
```

### 状态码说明

| code | 说明                       |
| ---- | -------------------------- |
| 200  | 成功                       |
| 400  | 请求参数错误               |
| 401  | 未授权（Token 无效或过期） |
| 403  | 权限不足                   |
| 404  | 资源不存在                 |
| 409  | 资源冲突（如重复注册）     |
| 500  | 服务器内部错误             |

---

## 1. 认证模块 (Auth)

### 1.1 用户注册

注册新用户，状态默认为 `pending`，需管理员审核。

- **URL:** `POST /api/auth/register`
- **认证:** 不需要

**请求参数:**

```json
{
  "phone": "13800138000",
  "name": "张三",
  "password": "your_password"
}
```

| 参数     | 类型   | 必填 | 说明               |
| -------- | ------ | ---- | ------------------ |
| phone    | string | 是   | 手机号（唯一标识） |
| name     | string | 是   | 用户姓名           |
| password | string | 是   | 密码               |

**响应示例:**

```json
{
  "code": 200,
  "msg": "注册成功，请等待审核"
}
```

**错误响应:**

| code | msg                        |
| ---- | -------------------------- |
| 400  | 手机号、姓名和密码不能为空 |
| 409  | 该手机号已注册             |

---

### 1.2 用户登录

验证用户凭据，返回 JWT Token。

- **URL:** `POST /api/auth/login`
- **认证:** 不需要

**请求参数:**

```json
{
  "phone": "13800138000",
  "password": "your_password"
}
```

**响应示例:**

```json
{
  "code": 200,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 1,
    "phone": "13800138000",
    "name": "张三",
    "role": "admin"
  }
}
```

**错误响应:**

| code | msg                                       |
| ---- | ----------------------------------------- |
| 400  | 手机号和密码不能为空                      |
| 401  | 手机号或密码错误                          |
| 403  | 账号尚未通过审核 / 账号审核未通过：{原因} |

---

### 1.3 获取待审核用户列表

获取所有状态为 `pending` 的用户。

- **URL:** `GET /api/auth/pending`
- **认证:** 需要
- **权限:** `admin` 或 `store_manager`

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "id": 2,
      "phone": "13900139000",
      "name": "李四",
      "status": "pending",
      "create_date": "2026-03-26 10:00"
    }
  ]
}
```

---

### 1.4 审核通过

审核通过用户并分配角色。

- **URL:** `POST /api/auth/approve/<user_id>`
- **认证:** 需要
- **权限:** `admin` 或 `store_manager`

**路径参数:**

| 参数    | 类型 | 说明    |
| ------- | ---- | ------- |
| user_id | int  | 用户 ID |

**请求参数:**

```json
{
  "role": "staff"
}
```

| 参数 | 类型   | 必填 | 可选值                            |
| ---- | ------ | ---- | --------------------------------- |
| role | string | 是   | `admin`, `store_manager`, `staff` |

**响应示例:**

```json
{
  "code": 200,
  "msg": "审核通过",
  "data": {
    "id": 2,
    "phone": "13900139000",
    "name": "李四",
    "role": "staff",
    "status": "approved"
  }
}
```

**错误响应:**

| code | msg                                             |
| ---- | ----------------------------------------------- |
| 400  | 无效角色，可选角色: admin, store_manager, staff |
| 403  | 店长无法分配管理员角色                          |
| 404  | 用户不存在                                      |

---

### 1.5 审核拒绝

拒绝用户注册申请。

- **URL:** `POST /api/auth/reject/<user_id>`
- **认证:** 需要
- **权限:** `admin` 或 `store_manager`

**路径参数:**

| 参数    | 类型 | 说明    |
| ------- | ---- | ------- |
| user_id | int  | 用户 ID |

**请求参数:**

```json
{
  "remark": "拒绝原因（选填）"
}
```

**响应示例:**

```json
{
  "code": 200,
  "msg": "已拒绝",
  "data": {
    "id": 2,
    "status": "rejected",
    "remark": "拒绝原因"
  }
}
```

---

### 1.6 获取全部用户

获取系统中所有用户。

- **URL:** `GET /api/users`
- **认证:** 需要
- **权限:** `admin`

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "phone": "admin",
      "name": "Administrator",
      "role": "admin",
      "status": "approved"
    }
  ]
}
```

---

### 1.7 修改用户角色

修改已有用户的角色。

- **URL:** `PUT /api/users/<user_id>/role`
- **认证:** 需要
- **权限:** `admin`

**路径参数:**

| 参数    | 类型 | 说明    |
| ------- | ---- | ------- |
| user_id | int  | 用户 ID |

**请求参数:**

```json
{
  "role": "store_manager"
}
```

**响应示例:**

```json
{
  "code": 200,
  "msg": "角色已更新",
  "data": {
    "id": 2,
    "role": "store_manager"
  }
}
```

---

### 1.8 删除用户（硬删除）

彻底删除指定用户，并清理其关联数据中的用户引用。

- **URL:** `DELETE /api/users/<user_id>`
- **认证:** 需要
- **权限:** `admin`

**路径参数:**

| 参数    | 类型 | 说明    |
| ------- | ---- | ------- |
| user_id | int  | 用户 ID |

**响应示例:**

```json
{
  "code": 200,
  "msg": "用户已删除",
  "data": {
    "id": 2,
    "phone": "13900139000",
    "name": "李四"
  }
}
```

**错误响应:**

| code | msg        |
| ---- | ---------- |
| 404  | 用户不存在 |

---

## 2. 订单模块 (Order)

### 2.1 创建订单

创建新订单。

- **URL:** `POST /api/create`
- **认证:** 需要

**请求参数:**

```json
{
  "order_id": "ORD20260326001",
  "customer_name": "客户A",
  "receiver": "收件人姓名",
  "receiver_phone": "13800138000",
  "address": "收件地址",
  "zip_code": "100000",
  "country": "中国",
  "tag_all": "标签",
  "cargo_count": 3,
  "remark": "备注信息",
  "salesman_id": 3,
  "quote": {
    "unit_price": 12.34,
    "surcharge": 5,
    "quote_remark": "创建订单时的首版报价"
  }
}
```

`salesman_id` 为所选业务员。`quote` 为可选字段；提供时，订单创建完成后复用报价服务自动生成第 1 版报价，报价人取 `salesman_id` 对应的业务员，不取接口操作人。

**响应示例:**

```json
{
  "code": 200,
  "msg": "创建成功并已生成报价",
  "uid": "订单UID",
  "data": {
    "quote": {
      "version_no": 1,
      "quoter_id": 3,
      "quoter_name": "业务员A"
    }
  }
}
```

**错误响应:**

| code | msg                          |
| ---- | ---------------------------- |
| 500  | Record Existed（订单已存在） |

---

### 2.2 获取订单列表

获取订单列表，支持分页、搜索和排序。

- **URL:** `GET /api/orders`
- **认证:** 需要

**查询参数:**

| 参数 | 类型   | 默认值      | 说明                       |
| ---- | ------ | ----------- | -------------------------- |
| p    | int    | 1           | 页码（从 1 开始）          |
| s    | int    | 30          | 每页数量                   |
| sf   | string | create_date | 排序字段                   |
| so   | int    | 1           | 排序方向（1=降序, 0=升序） |
| q    | string | ""          | 搜索订单、客户、收件人、业务员等关键词 |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "uid": "abc123",
      "order_id": "ORD20260326001",
      "customer_name": "客户A",
      "receiver": "收件人",
      "cargo_count": 3,
      "create_date": "2026-03-26 10:00"
    }
  ],
  "total": 100
}
```

---

### 2.3 获取单个订单

根据 UID 获取订单详情。

- **URL:** `GET /api/orders/<uid>`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 订单唯一标识 |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "uid": "abc123",
    "order_id": "ORD20260326001",
    "customer_name": "客户A",
    "receiver": "收件人",
    "receiver_phone": "13800138000",
    "address": "收件地址",
    "cargo_count": 3,
    "current_version": 3,
    "edit_policy": {
      "order_fields": true,
      "transportation": true,
      "order_weight": true,
      "salesman": true,
      "customer_assignment": true,
      "cargo_content": true,
      "cargo_weight": true,
      "box_content": true,
      "box_weight": true,
      "tracking_numbers": true,
      "box_workers": true,
      "box_membership": true,
      "archive_or_delete": true,
      "fully_outbound": true
    },
    "cargo_uid_list": ["cargo1", "cargo2", "cargo3"]
  }
}
```

`edit_policy` 由服务端按当前角色计算，前端应直接使用。全部出库或已有收据均不再阻止编辑；`fully_outbound` 沿用所有有效装箱单箱子均为 `status=1` 且有转单号的兼容判断，不参与编辑权限计算。详情不再返回订单业务锁、财务锁和修订窗口字段。

---

### 2.4 更新订单

更新订单信息。

- **URL:** `PUT /api/orders/<uid>`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 订单唯一标识 |

**请求参数:**

```json
{
  "receiver": "新收件人",
  "address": "新地址"
}
```

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 2.5 删除单个订单

删除指定订单。

- **URL:** `DELETE /api/orders/<uid>`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 订单唯一标识 |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 2.6 批量删除订单

批量删除多个订单。

- **URL:** `DELETE /api/orders`
- **认证:** 需要

**请求参数:**

```json
{
  "uid_list": ["uid1", "uid2", "uid3"]
}
```

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 2.7 为订单添加货物

为订单添加新的货物/包裹。

- **URL:** `POST /api/orders/<uid>/add_cargo`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 订单唯一标识 |

**请求参数:**

```json
{
  "cargo_count": 2
}
```

| 参数        | 类型 | 必填 | 说明                         |
| ----------- | ---- | ---- | ---------------------------- |
| cargo_count | int  | 是   | 要添加的货物数量（必须 > 0） |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "uid": "cargo4",
      "origin_id": "ORD20260326001-4",
      "status": 0
    }
  ],
  "cargo_id_list": ["cargo1", "cargo2", "cargo3", "cargo4"]
}
```

---

### 2.8 获取订单版本列表

- **URL:** `GET /api/orders/<uid>/versions?p=1&s=20`
- **认证:** 需要
- **权限:** `admin`、`store_manager`
- **分页:** `p` 默认 1；`s` 默认 20，最大 100

版本按 `version_no` 倒序返回。`change_summary` 只返回本版涉及的实体、操作和字段；完整前后值通过版本详情获取。

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

硬删除订单后，只要知道其 `order_uid`，仍可读取版本列表。

### 2.9 获取订单版本详情

- **URL:** `GET /api/orders/<uid>/versions/<version_no>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`

响应在版本元数据之外返回：

- `changes`：该版增量，每项包含 `sequence_no`、`entity_type`、`entity_uid`、`operation`、`fields`、`before_data`、`after_data`。
- `snapshot`：从 V1 顺序应用增量后得到的完整订单、普通货物和箱子快照。
- `last_existing_snapshot`：仅删除订单版本返回，用于展示删除前最后一份完整订单。

`entity_type` 为 `order`、`cargo` 或 `box`；`operation` 为 `create`、`update` 或 `delete`。找不到版本时返回 `404`。`item_details` 始终以完整前后列表返回。

### 2.10 查询已删除订单历史

- **URL:** `GET /api/order-history?deleted_only=1&q=&p=1&s=20`
- **认证:** 需要
- **权限:** `admin`、`store_manager`

`deleted_only` 默认是 `1`，返回最新版本为删除墓碑的订单；传 `0`、`false` 或 `no` 时返回所有订单的最新历史元数据。`q` 仅匹配订单 UID、订单号或客户名称。响应的 `data` 为 `{ items, total, page, page_size }`，其中 `items` 使用与版本列表相同的元数据结构。

历史旧 `transfer_id` 和 `waybill_id` 不进入订单列表或删除历史的全局搜索，只能在已知订单的版本详情中查看。

订单历史为只读且长期保留。系统没有恢复旧版本或删除版本的普通 UI/API。字段、重建和保留规则详见 [API v1.6](API-v1.6.md)。

---

## 3. 货物模块 (Cargo)

### 3.1 获取订单货物列表

获取订单下所有货物，包含实时物流状态。

- **URL:** `GET /api/orders/<uid>/cargo`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 订单唯一标识 |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "uid": "cargo1",
      "origin_id": "ORD20260326001-1",
      "status": 1,
      "waybill_id": "SF1234567890",
      "transfer_id": "TF001",
      "weight": 1.5,
      "count": 2,
      "tracking": {
        "status": "delivered",
        "last_update": "2026-03-26 15:00"
      }
    }
  ]
}
```

---

### 3.2 获取所有货物运单信息

获取所有订单下货物的原单号和转单号（运单号）。

- **URL:** `GET /api/cargo`
- **认证:** 需要

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "order_uid_1": [
      {
        "transfer_id": "TF001",
        "waybill_id": "SF1234567890"
      }
    ]
  }
}
```

---

### 3.3 批量删除货物

批量删除货物。

- **URL:** `DELETE /api/cargo`
- **认证:** 需要

**请求参数:**

```json
{
  "cargo_id_list": ["cargo1", "cargo2"]
}
```

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 3.4 更新货物信息

更新货物信息，运单号变更时会自动注册物流追踪。

字段语义统一为：`transfer_id` 是原单号，`waybill_id` 是转单号（运单号）。历史旧值不参与订单列表全局搜索。

货物状态进入出库（`status=1`）或任一后续物流状态后，`weight` 不可修改；待出库（`status=0`）货物仍可按权限称重。首次登记转单号时允许在同一请求中提交最终重量，成功后状态转为出库。后续修改重量返回 HTTP `409`：

```json
{
  "code": 409,
  "msg": "货物已出库，重量不可修改；如需调整重量，请使用新的原单号创建包裹"
}
```

`status` 和出库日期 `date` 由出库/撤销出库流程维护，不能通过本接口直接提交；提交时返回 HTTP `400`。

- **URL:** `PUT /api/cargo/<uid>`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 货物唯一标识 |

**请求参数:**

```json
{
  "waybill_id": "SF9876543210",
  "transfer_id": "TF002",
  "weight": 2.0,
  "count": 3
}
```

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 3.5 货物入库

录入货物重量和件数。

- **URL:** `POST /api/cargo/<uid>/input`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 货物唯一标识 |

**请求参数:**

```json
{
  "weight": 1.5,
  "count": 2
}
```

| 参数   | 类型   | 必填 | 说明 |
| ------ | ------ | ---- | ---- |
| weight | number | 是   | 重量 |
| count  | int    | 是   | 件数 |

若货物已处于出库或后续状态，本接口修改重量会返回 HTTP `409`。箱子经专用撤销出库接口回到待出库状态后可重新称重。

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 3.6 货物出库

标记货物为已发货状态。

- **URL:** `POST /api/cargo/<uid>/output`
- **认证:** 不需要 Token（仅 IP 限制）

**路径参数:**

| 参数 | 类型   | 说明         |
| ---- | ------ | ------------ |
| uid  | string | 货物唯一标识 |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "uid": "cargo1",
    "origin_id": "ORD20260326001-1",
    "date": "2026-03-26 15:00",
    "customer_name": "客户A"
  }
}
```

---

### 3.7 生成 Excel 导出文件

根据指定模式生成 Excel 文件。

- **URL:** `POST /api/cargo/excel/<mode>`
- **认证:** 需要

**路径参数:**

| 参数 | 类型   | 说明     |
| ---- | ------ | -------- |
| mode | string | 导出模式 |

**可选模式:**

`jifei`, `tongcang`, `huanshitong`, `jinfeiqi`, `jinlong`, `xinghang`, `tongcangups`, `yaxuan`, `kehu`, `jinlong_kuaidi`, `WE`

**请求参数:**

```json
{
  "uid_list": ["order_uid_1", "order_uid_2"],
  "cargo_list": ["cargo_uid_1", "cargo_uid_2"]
}
```

| 参数       | 类型  | 必填 | 说明                      |
| ---------- | ----- | ---- | ------------------------- |
| uid_list   | array | 是   | 订单 UID 列表             |
| cargo_list | array | 否   | 货物 UID 列表（可选筛选） |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "document_id": "export_20260326_150000"
  }
}
```

---

### 3.8 下载 Excel 文件

下载已生成的 Excel 导出文件。

- **URL:** `GET /api/cargo/excel/<document_id>`
- **认证:** 需要

**路径参数:**

| 参数        | 类型   | 说明                      |
| ----------- | ------ | ------------------------- |
| document_id | string | 文件 ID（从生成接口获取） |

**响应:** 返回 Excel 文件流 (`application/vnd.ms-excel`)

---

### 3.9 下载货物标签 PDF

下载货物标签 PDF。

- **URL:** `GET /api/cargo/pdf/<cargo_list>`
- **认证:** 不需要 Token

**路径参数:**

| 参数       | 类型   | 说明                      |
| ---------- | ------ | ------------------------- |
| cargo_list | string | 货物 ID 列表，用 `_` 分隔 |

**示例:** `/api/cargo/pdf/cargo1_cargo2_cargo3`

**响应:** 返回 PDF 文件流 (`application/pdf`)

---

### 3.10 上传转运单

上传转运单文件，按订单分别更新运单号并补登记出库。失败订单仅回滚自己的上传记录，其他订单继续保存。部分成功返回 HTTP 200、`code=207`，响应 `failed_list` 仅列未保存记录及原因；重复相同号码的已保存记录仍计为成功。保存和物流追踪注册的结果分别报告。完整契约见 [API v1.38](API-v1.38-partial-waybill-upload.md)。

- **URL:** `POST /api/order/upload/transfer_table`
- **认证:** 需要
- **Content-Type:** `multipart/form-data`

**请求参数:**

| 参数     | 类型   | 必填 | 说明       |
| -------- | ------ | ---- | ---------- |
| file     | File   | 是   | 转运单文件 |
| filename | string | 是   | 文件名     |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success",
  "cargo_count": 10,
  "cargo_list": {},
  "success_list": [],
  "success_items": [],
  "failed_list": [],
  "tracking_error": null
}
```

---

### 3.11 原子更新箱内容和操作员

- **URL:** `PUT /api/box/<uid>`
- **认证:** 需要
- **权限:** 沿用现有箱子编辑角色

请求可在保存箱内容时一并提交 `worker_ids`：

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

`worker_ids` 最多包含 4 个正整数；传空数组表示清空操作员，未传表示保留。箱内容、操作员和对应订单版本在同一事务内提交，并且一次请求最多生成一个订单版本。原 `PUT /api/box/<uid>/workers` 和 `POST /api/box/<uid>/workers/add` 继续兼容。

箱子一旦出库，箱号 `box_number` 和原单号 `transfer_id` 不可修改，撤销出库后仍保持固定。转单号 `waybill_id` 继续按角色权限修改，原成本、收款和奖金历史继续保留。改箱号或原单号返回 `409`，具体规则见 [API v1.17](API-v1.17.md)。

---

## 4. 客户模块 (Customer)

### 4.1 获取客户列表

获取所有客户名称列表。

- **URL:** `GET /api/customer_list`
- **认证:** 需要

**响应示例:**

```json
{
  "code": 200,
  "data": ["客户A", "客户B", "客户C"]
}
```

---

### 4.2 获取客户收件人列表

获取指定客户名下的收件人列表。

- **URL:** `GET /api/receiver_list/<customer_name>`
- **认证:** 需要

**路径参数:**

| 参数          | 类型   | 说明     |
| ------------- | ------ | -------- |
| customer_name | string | 客户名称 |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "receiver_id": "recv001",
      "receiver": "收件人A"
    }
  ]
}
```

---

### 4.3 获取收件人详情列表

获取客户名下所有收件人的完整信息。

- **URL:** `GET /api/receiver_info_list/<customer_name>`
- **认证:** 需要

**路径参数:**

| 参数          | 类型   | 说明     |
| ------------- | ------ | -------- |
| customer_name | string | 客户名称 |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "receiver_id": "recv001",
      "receiver": "收件人A",
      "phone": "13800138000",
      "address": "详细地址",
      "zip_code": "100000",
      "country": "中国"
    }
  ]
}
```

---

### 4.4 获取单个收件人信息

获取单个收件人的详细信息。

- **URL:** `GET /api/receiver_info/<receiver_id>`
- **认证:** 需要

**路径参数:**

| 参数        | 类型   | 说明      |
| ----------- | ------ | --------- |
| receiver_id | string | 收件人 ID |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "receiver_id": "recv001",
    "receiver": "收件人A",
    "phone": "13800138000",
    "address": "详细地址"
  }
}
```

---

### 4.5 删除收件人

删除指定客户名下的收件人。

- **URL:** `POST /api/del/<customer_name>/<receiver_id>`
- **认证:** 需要

**路径参数:**

| 参数          | 类型   | 说明      |
| ------------- | ------ | --------- |
| customer_name | string | 客户名称  |
| receiver_id   | string | 收件人 ID |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 4.6 删除客户

删除客户及其所有收件人（级联删除）。

- **URL:** `POST /api/del_customer/<customer_name>`
- **认证:** 需要

**路径参数:**

| 参数          | 类型   | 说明     |
| ------------- | ------ | -------- |
| customer_name | string | 客户名称 |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 4.7 下载 Excel 模板

下载预填地址的 Excel 模板。

- **URL:** `GET /api/excel`
- **认证:** 不需要

**查询参数:**

| 参数           | 类型   | 必填 | 说明           |
| -------------- | ------ | ---- | -------------- |
| address        | string | 否   | 预填地址       |
| zip_code       | string | 否   | 预填邮编       |
| country        | string | 否   | 预填国家       |
| receiver       | string | 否   | 预填收件人     |
| receiver_phone | string | 否   | 预填收件人电话 |

**响应:** 返回 Excel 文件流

---

### 4.8 获取所有客户详细信息（含敏感字段）

获取所有客户的详细信息，包括phone和wechat等敏感字段。

业务员只返回本人创建的客户；管理员、店长仍可查看全部。创建人、单笔读写限制与订单联系方式接口见 [API v1.23](API-v1.23-customer-permissions.md)。

- **URL:** `GET /api/customers_detail`
- **认证:** 需要
- **权限:** `admin`（管理员）、`store_manager`（店长）、`salesperson`（业务员）
- **审计日志:** ✓ 会记录访问日志

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "name": "客户A",
      "phone": "13912345678",
      "wechat": "wx_customer_a"
    },
    {
      "id": 2,
      "name": "客户B",
      "phone": "",
      "wechat": ""
    }
  ]
}
```

**错误响应:**

| code | msg               |
| ---- | ----------------- |
| 401  | 未登录或token无效 |
| 403  | 权限不足          |

**说明:**
- 只有admin、store_manager、salesperson角色可以访问
- clerk、finance、employee等角色无权访问（返回403）
- 所有访问会记录到`log/audit_sensitive_access.log`审计日志

---

### 4.9 获取单个客户详细信息（含敏感字段）

获取单个客户的详细信息，包括phone和wechat等敏感字段。

业务员仅可读取本人创建的客户，超出范围返回 `403`。订单详情改用 `GET /api/orders/<uid>/customer-contact`，按订单当前业务员校验，详见 [API v1.23](API-v1.23-customer-permissions.md)。

- **URL:** `GET /api/customer_detail/<customer_id>`
- **认证:** 需要
- **权限:** `admin`（管理员）、`store_manager`（店长）、`salesperson`（业务员）
- **审计日志:** ✓ 会记录访问日志

**路径参数:**

| 参数        | 类型 | 说明              |
| ----------- | ---- | ----------------- |
| customer_id | int  | 客户ID（主键） |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "id": 1,
    "name": "客户A",
    "phone": "13912345678",
    "wechat": "wx_customer_a"
  }
}
```

**错误响应:**

| code | msg               |
| ---- | ----------------- |
| 401  | 未登录或token无效 |
| 403  | 权限不足          |
| 404  | Customer not found |

**说明:**
- 使用主键ID查询，避免回表，性能最优
- 只有admin、store_manager、salesperson角色可以访问
- 所有访问会记录到`log/audit_sensitive_access.log`审计日志

---

### 4.10 更新客户联系信息

更新客户的phone和wechat联系信息。

- **URL:** `POST /api/customer_info/<customer_name>`
- **认证:** 需要
- **权限:** `admin`（管理员）、`store_manager`（店长）、`salesperson`（业务员）
- **审计日志:** ✓ 会记录访问日志

**路径参数:**

| 参数          | 类型   | 说明     |
| ------------- | ------ | -------- |
| customer_name | string | 客户名称 |

**请求参数:**

```json
{
  "phone": "13912345678",
  "wechat": "wx_new_wechat"
}
```

| 参数   | 类型   | 必填 | 说明         |
| ------ | ------ | ---- | ------------ |
| phone  | string | 否   | 客户电话     |
| wechat | string | 否   | 客户微信号   |

**响应示例:**

```json
{
  "code": 200,
  "msg": "Customer info updated successfully"
}
```

**错误响应:**

| code | msg                                  |
| ---- | ------------------------------------ |
| 401  | 未登录或token无效                    |
| 403  | 权限不足                             |
| 500  | Failed to update customer info: ... |

**说明:**
- `phone`和`wechat`都是可选的，可以只更新其中一个
- 如果客户不存在，会自动创建新客户
- 传入空字符串会清空对应字段
- 所有更新操作会记录到`log/audit_sensitive_access.log`审计日志

---

## 5. 日志与审计

### 5.1 敏感数据访问审计日志

系统会记录所有对客户敏感信息（phone、wechat）的访问和修改操作。

**日志位置:** `log/audit_sensitive_access.log`

**日志格式:**
```
2026-04-03 10:30:00 | INFO | User[ID=1, Role=admin, Name=管理员] performed 'view_all' from IP[127.0.0.1]
2026-04-03 10:31:00 | INFO | User[ID=2, Role=salesperson, Name=业务员] performed 'view_single' on Customer[ID:5] from IP[192.168.1.100]
2026-04-03 10:32:00 | INFO | User[ID=1, Role=admin, Name=管理员] performed 'update' on Customer[客户A] from IP[127.0.0.1]
```

**记录的操作类型:**
- `view_all`: 查看所有客户详情
- `view_single`: 查看单个客户详情
- `update`: 更新客户联系信息

### 5.2 操作日志列表

- **URL:** `GET /api/logs`
- **认证:** 需要
- **权限:** `admin`
- **查询参数:** `p` 页码、`s` 每页条数、`sf` 排序字段、`so` 排序方向（`1`倒序，`0`正序）

**响应示例:**

```json
{
  "code": 200,
  "total": 123,
  "page": 1,
  "page_size": 10,
  "data": [
    {
      "id": 1,
      "log_date": "2026-03-26 15:00:00",
      "desc": "Create order.",
      "user_name": "张三",
      "user_role": "admin",
      "pc_name": "WMS-PC",
      "ip": "192.168.1.1",
      "method": "POST",
      "kwargs": {},
      "json": {}
    }
  ]
}
```

### 5.3 系统审计日志列表

- **URL:** `GET /api/audit-logs`
- **认证:** 需要
- **权限:** `admin`
- **查询参数:** `p` 页码、`s` 每页条数、`sf` 排序字段、`so` 排序方向（`1`倒序，`0`正序）

**响应示例:**

```json
{
  "code": 200,
  "total": 50,
  "page": 1,
  "page_size": 10,
  "data": [
    {
      "id": 1,
      "event_type": "order_quote",
      "target_type": "order",
      "target_id": "ORDER001",
      "action": "quote_submit",
      "operator_name": "张三",
      "operator_role": "admin",
      "before_data": null,
      "after_data": {},
      "remark": "提交报价",
      "ip": "192.168.1.1",
      "create_date": "2026-03-26 15:00:00"
    }
  ]
}
```

订单全部出库不再自动锁定，已有收据也不再限制重量、客户归属和箱子成员关系。具体变更见 [API v1.16](API-v1.16.md)。

---

## 6. 品名管理

### 6.1 获取品名列表

- **URL:** `GET /api/goods-names`
- **认证:** 需要
- **查询参数:** `lang` 可选，取值为 `cn` 或 `en`

响应中的英文品名包含可空的 `category` 子标题字段；空值由前端显示为“未分类”。

```json
{
  "code": 200,
  "data": [
    {
      "id": 1,
      "name": "SHOES",
      "lang": "en",
      "category": "鞋包",
      "create_date": "2026-07-14 10:00",
      "update_date": "2026-07-14 10:00"
    }
  ]
}
```

### 6.2 新增、修改和删除品名

- **新增:** `POST /api/goods-names`，管理员权限，请求体为 `{ "name": "SHOES", "lang": "en", "category": "鞋包" }`
- **修改:** `PUT /api/goods-names/<id>`，管理员权限，请求体为 `{ "name": "TRAINER", "category": "鞋包" }`；未传 `category` 时保留原分类
- **删除:** `DELETE /api/goods-names/<id>`，管理员权限
- 同一语言下的品名按名称忽略大小写判重，重复新增或修改返回 `409`

### 6.3 批量导入英文品名

- **URL:** `POST /api/goods-names/import`
- **认证/权限:** 需要，`admin`
- **说明:** 在单个事务内导入；文件解析由管理页完成，接口接收解析后的英文品名列表

```json
{
  "items": [
    { "name": "SHOES", "category": "鞋包" },
    { "name": "TRAINER", "category": "鞋包" }
  ]
}
```

数据库中已有或本批次内重复的英文品名会按名称忽略大小写跳过：

```json
{
  "code": 200,
  "data": {
    "created_count": 1,
    "skipped_count": 1,
    "skipped": [
      { "name": "SHOES", "category": "鞋包", "reason": "already_exists" }
    ]
  }
}
```

### 6.4 海关编码映射

- **列表:** `GET /api/customs-codes`，所有已登录用户可访问
- **新增:** `POST /api/customs-codes`，管理员权限，请求体为 `{ "name": "SHOES", "code": "6404199000" }`
- **修改:** `PUT /api/customs-codes/<id>`，管理员权限
- **删除:** `DELETE /api/customs-codes/<id>`，管理员权限
- 每个品名只保留一条映射，品名匹配忽略大小写

### 6.5 批量导入海关编码

- **URL:** `POST /api/customs-codes/import`
- **认证/权限:** 需要，`admin`
- **请求体:** `{ "items": [{ "name": "SHOES", "code": "6404199000" }] }`
- 已有同名映射且编码变化时更新；编码未变化或文件内同名重复时跳过
- 响应的 `data` 包含 `created_count`、`updated_count`、`skipped_count` 和 `skipped`

装箱单箱子的 `item_details` 每项支持可选的 `customs_code` 字段：

```json
{
  "item_name": "SHOES",
  "customs_code": "6404199000",
  "piece_count": 2
}
```

---

## 7. 报价、收款与应收账款

所有金额均为 CNY。总金额保留 2 位小数，每公斤单价和跟单奖金费率保留 4 位小数，重量保留 3 位小数。

### 7.1 订单报价

- **列表:** `GET /api/orders/<uid>/quotes`
- **创建:** `POST /api/orders/<uid>/quotes`，仅允许订单当前 `salesman_id` 对应的 `salesperson`；订单未分配业务员或操作者不是当前业务员时返回 `403`
- **兼容:** 请求和响应暂时保留 `quoted_price`，其值与 `unit_price` 相同

```json
{
  "unit_price": 12.34,
  "surcharge": 5,
  "quote_remark": "含偏远附加费"
}
```

响应增加 `weight_snapshot`、`billing_weight`、`current_weight`、`receivable_amount`、`effective_date`、`is_effective` 和 `validity_status`。`weight_snapshot` 为订单原始总重量，`billing_weight` 为每个未归档包裹分别向上取整后再求和的计费重量；`receivable_amount` 按 `round(billing_weight × unit_price + surcharge, 2)` 计算。低于渠道 `min_price` 的每公斤单价进入 `pending`，附加费不参与最低报价判断。

`validity_status` 取值：`effective`、`pending`、`rejected`、`superseded`。有效报价使用当前未归档包裹计算原始重量、计费重量和应收，报价快照保留为历史记录。全部出库及已有收据不再限制编辑或报价；编辑仍遵循角色权限。

- **待审核报价:** `GET /api/finance/quote-approvals`，权限为 `admin`
- **审核:** `PUT /api/finance/quote-approvals/<quote_id>`，请求体为 `{ "action": "approve|reject", "review_remark": "..." }`
- **双语报价单:** `GET /api/orders/<uid>/quote-pdf`

订单全部出库后仍可提交新报价和批准待审报价。已有收据历史的订单重报价真正生效后，继续按新旧有效报价应收差生成待处理差价单。

### 7.2 可收款订单与收款单

- **可收款订单:** `GET /api/receivables/orders?customer_id=<id>&q=<订单号>&p=1&s=20`，权限为 `salesperson`、`admin`。`customer_id` 可选；无论是否传入，都只返回 `实时应收 > 已审核 + 待审核` 且不存在待审核或已批准结清收据的当前可收款订单
- **旧创建接口已停用:** `POST /api/receipts` 返回410。新收付款使用 v1.22 的 `/api/finance/v2/payments`；以下订单选款及结清规则仅供解释历史记录。
- **收款单列表:** `GET /api/receipts?p=1&s=20&status=pending&q=<单号或客户>`
- **收款单详情:** `GET /api/receipts/<id>`
- **双语 PDF:** `GET /api/receipts/<id>/pdf`

可收款订单可传 `order_uid` 精确查询当前订单。管理员及财务查询收款单列表可传 `owner_id` 按创建人筛选，不传仍查看全部；业务员始终仅查看本人创建的收款单。管理员在收款管理页面默认选择本人，允许切换负责人或全部。完整参数契约见 [API v1.18](API-v1.18.md)。

```json
{
  "customer_id": 1,
  "receipt_date": "2026-08-27",
  "payment_method": "bank_transfer",
  "settlement_status": "unsettled",
  "remark": "首笔部分收款",
  "items": [
    { "order_uid": "ORDER-UID", "amount": 80 }
  ]
}
```

`payment_method` 可取 `cash`、`bank_transfer`、`wechat`、`alipay`、`other`。一张收款单只能包含一个客户的订单；业务员只能登记当前有效报价人为本人的订单，管理员可代登记。待审核金额立即占用可收余额，金额必须大于 0 且不能超额。单号格式为 `RCPT-YYYYMMDD-xxxxxx`。

审核状态 `status` 为 `pending`、`approved`、`rejected`。三种状态均可打印，PDF 响应为 Base64 编码，字段 `mime_type` 为 `application/pdf`。

结清状态 `settlement_status` 为 `settled`（已结清）或 `unsettled`（未结清），统一作用于整张收据。未传时按所选订单 `应收 − 已审核实收 − 已生效结清差额 − 本次收款` 合计小于30元默认已结清，否则未结清；默认判断不扣其他待审核金额，业务员可以覆盖。历史记录为空并保持原逻辑。结清须审核通过后生效，保留实际收款及原报价，明细新增最终 `settlement_difference` 和待审 `preview_settlement_difference`。完整规则见 [API v1.5](API-v1.5.md)。

#### 7.2.1 订单编辑与箱子重新入库

订单锁定、解锁、重新锁定及修订窗口流程已删除，原 `receipt-unlock`、`receipt-relock` 和管理员开放修订查询接口已移除。历史修订记录继续保留，不影响当前操作。

订单与包裹的重量、客户归属、箱子增删、分配和解绑均按普通角色权限处理，不因已有收据历史受限。已出库包裹的重量约束独立保留；装箱单箱子撤销出库后可重新称重。

`clerk` 属于箱子编辑角色，可编辑箱子内容、原单号、转单号和操作员；箱子重量仍由独立的 `box_weight` 角色权限控制。

`POST /api/box/<uid>/undo-ship` 允许管理员和店长撤销装箱单箱子出库：清空转单号及出库时间，状态恢复为待出库（`0`）；保留订单归属、原单号、重量及奖金。当前成本归档，出库记录、原成本金额与收款历史继续保留，再次出库创建新成本和新的出库记录。成功后前端刷新装箱单箱子列表。

删除被报价、成本或收款外键引用的订单，以及有成本记录的箱子时，执行归档并保留历史；无引用记录仍可物理删除。订单归档在同一事务内级联归档关联货物/箱子、成本、报价、差价单和收款明细。

#### 7.2.2 重报价差价单

`GET /api/receivable-adjustments?status=pending&q=&p=1&s=20` 查询重报价生效后自动生成的待处理差价。`delta_amount` 为新应收减旧应收；正数表示待补收，负数表示待退款，零差不生成。差价单不代表现金已经收取或退还，也不进入收款金额汇总。详细规则见 [API v1.7](API-v1.7.md)。

`GET /api/receivable-adjustments/<id>` 查询单笔差价。列表和详情新增 `customer_id`、`approved_received`、`pending_amount`、`available_amount`、`collection_blocked_reason`。业务员按订单当前有效报价负责人查看，管理员及财务查看全部。

差价列表可传 `order_uid` 精确查询订单；管理员及财务可传 `owner_id` 按当前有效报价人筛选。业务员的跟单范围不受传入 `owner_id` 影响，见 [API v1.18](API-v1.18.md)。

`POST /api/receipts` 明细可传 `adjustment_id` 登记补收；关联差价的收款单只包含一笔明细并固定使用 `unsettled`，支持分次实收且不自动减免余款。同差价已有待审补收单时禁止重复登记；批准后更新差价余额，补足差价或订单实际应收时关闭待补收任务，驳回释放占用。退款差价仍只读。新增外键需先执行数据库迁移，完整契约见 [API v1.8](API-v1.8.md)。

### 7.3 收款审核

- **URL:** `PUT /api/finance/receipts/<id>/review`
- **权限:** `finance`、`admin`
- **请求:** `{ "action": "approve|reject", "review_remark": "..." }`

创建人不能审核自己的收款单。驳回必须填写审核意见；驳回单永久保留，原待审核占用自动释放。只有 `approved` 明细计入已收账款。

已结清收据批准前须先处理关联订单的其他待审核收据，否则整张保持待审核并返回相关单号。批准时固化结清差额；差额不计入实际收入。待审核结清收据暂停关联订单新增收据，驳回后解除限制。

### 7.4 应收账款台账

- **URL:** `GET /api/finance/accounts-receivable`
- **权限:** `finance`、`admin`
- **参数:** `date_from=YYYY-MM-DD`、`date_to=YYYY-MM-DD`、`customer_id`、`owner_id`、`status=unpaid|partial|paid`、`q`、`p`、`s`。`as_of` 暂作为 `date_to` 的兼容参数保留

响应 `data.items` 按订单返回负责人、报价生效日、原始重量 `weight_snapshot`、向上取整后的计费重量 `billing_weight`、应收、已收、结清差额 `settlement_difference`、未收、待审核占用与结清状态；`data.totals` 返回报价生效日在起止日期（含）之间的订单合计（包括结清差额）。收款和结清状态按 `date_to` 当日 23:59:59 重建；生效结清订单的未收为0、状态为 `paid`，收入仍只累计实际收款。

### 7.5 跟单奖金费率

- **列表:** `GET /api/finance/sales-bonus-rates`
- **新增版本:** `POST /api/finance/sales-bonus-rates`
- **权限:** `finance`、`admin`

```json
{
  "effective_from": "2026-08-01",
  "rate_per_kg": 0.5,
  "remark": "八月起执行"
}
```

同一生效日期只能有一个版本。历史版本不可覆盖；跟单奖金按报价生效日选择当时有效费率，计算为 `weight_snapshot × rate_per_kg`。

### 7.6 供应商导出报价校验

Excel 模板接口增加布尔字段 `requires_valid_quote`，新增模板默认 `true`。`POST /api/cargo/excel/<mode>` 在生成受限模板前校验整批订单；任一订单无有效报价时整批返回 `409`：

```json
{
  "code": 409,
  "msg": "部分订单尚无有效报价或重量已变化",
  "data": {
    "blocked_orders": [
      { "uid": "ORDER-UID", "order_id": "ERP-001", "reason": "stale" }
    ]
  }
}
```

硬编码 `kehu` 客户转单号列表不检查报价；前端 `wayBill` 面单导出也不检查报价。受限导出成功或被拦截均写入系统审计日志。

---

## 8. 其他

### 8.1 获取客户端 IP

获取当前请求的客户端 IP 地址。

- **URL:** `GET /ip`
- **认证:** 不需要

**响应示例:**

```
192.168.1.1
```

---

## 角色权限说明

| 角色            | 说明     | 权限范围                                      |
| --------------- | -------- | --------------------------------------------- |
| `admin`         | 管理员   | 所有权限                                      |
| `store_manager` | 店长     | 除管理员专属外的所有权限，不能分配 admin 角色 |
| `salesperson`   | 业务员   | 报价、收款登记、本人跟单与奖金查询            |
| `finance`       | 财务     | 应收台账、收款审核、奖金配置                  |
| `worker`        | 操作人员 | 本人工作详情和操作奖金查询                    |
| `clerk`         | 文员     | 基础业务操作                                  |

---

## 初始管理员账号

Docker 部署时通过环境变量配置初始管理员：

| 环境变量       | 默认值        | 说明           |
| -------------- | ------------- | -------------- |
| ADMIN_PHONE    | admin         | 管理员用户名   |
| ADMIN_PASSWORD | admin123      | 管理员密码     |
| ADMIN_NAME     | Administrator | 管理员显示名称 |

---

## 订单版本发布步骤

生产发布必须先停止业务写入并备份数据库，然后按顺序执行：

1. `alembic upgrade head`
2. `python -m scripts.backfill_order_versions`（幂等，失败后保持停写并重跑）
3. 核对脚本输出的 `orders`、`baseline_imports`、`v1_coverage` 和 `verified`
4. 确认 `verified=True`（即 `orders == v1_coverage`），并在首次冻结发布中确认 `orders == baseline_imports == v1_coverage`
5. 抽查 V1 完整快照后，再发布应用并恢复写入

`baseline_imports` 只统计 V1 基线导入，`v1_coverage` 统计所有 V1（包括新订单的 `order_created`）；脚本的 `verified` 只比较 `orders` 与 `v1_coverage`。写路径的“缺少基线时自动补 V1”仅是安全兜底，不能代替正式回填。历史长期保留，业务数据硬删除不清除版本，也没有普通历史删除 API。上线前已经硬删除的数据无法补录，不从旧操作日志推断或回放历史。完整迁移与校验说明见 [API v1.6](API-v1.6.md)。

---

## 按需生成订单号和原单号

`POST /api/orders/<order_uid>/generate-order-number` 与 `POST /api/orders/<order_uid>/cargo/<cargo_uid>/generate-original-number` 允许管理员、店长、业务员和文员在订单详情中为指定目标生成并保存号码。随机号码统一为 `D` 开头、`L` 结尾，中间保留首位 `8` 的 9 位数字，例如 `D800012345L`。跨订单号和原单号查重（含归档），并串行处理并发生成，不修改数据库唯一约束；手动输入和已保存号码保持原样。请求可传 `{ "expected_value": "页面已保存值" }` 防止覆盖已被他人修改的号码。箱子出库后的标识保护继续生效，生成不会触发出库。完整契约见 [API v1.25](API-v1.25-auto-numbers.md) 和 [API v1.32](API-v1.32-shipping-layout-and-number-format.md)。

*文档更新时间: 2026-10-07*
