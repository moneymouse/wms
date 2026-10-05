# WMS Backend API 接口文档

**Base URL:** `http://localhost:5001`

**版本:** 1.17

---

订单不再提供锁定、解锁或修订窗口；装箱单箱子操作栏恢复管理员和店长的“撤销出库”按钮。

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
  "remark": "备注信息"
}
```

**响应示例:**

```json
{
  "code": 200,
  "uid": 3232112,
  "msg": "success"
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
| q    | string | ""          | 搜索关键词                 |

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

前端以服务端 `edit_policy` 控制角色权限。全部出库及已有收据均不再禁用订单、客户归属、重量或包裹成员编辑；已出库包裹自身的重量限制仍有效，箱子重新入库后可称重。

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

### 2.8 订单修改历史前端契约

订单详情标题旁的“修改历史”按钮只对 `admin` 和 `store_manager` 显示。订单列表中的“已删除订单历史”入口使用相同权限。三个只读接口为：

| 用途 | 接口 |
| --- | --- |
| 版本列表 | `GET /api/orders/<uid>/versions?p=1&s=20` |
| 版本详情 | `GET /api/orders/<uid>/versions/<version_no>` |
| 删除历史 | `GET /api/order-history?deleted_only=1&q=&p=1&s=20` |

版本列表和删除历史的响应均包装在 `data` 中：

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

版本详情在同一元数据结构上增加：

- `changes[]`：本次增量，包含 `before_data` 和 `after_data`，用于“旧值 → 新值”。
- `snapshot`：目标版本的完整 `order`、`cargos`、`boxes` 和 `deleted` 状态。
- `last_existing_snapshot`：仅硬删除版本返回，用于展示删除前完整订单。

`item_details` 是完整数组，应以前后两张表展示，不按数组下标生成逐行 diff。`entity_type` 为 `order|cargo|box`，`operation` 为 `create|update|delete`。

历史抽屉行为要求：

- 列表按版本号倒序分页，展开项显示字段差异，“查看该版本”显示完整快照。
- 保存操作只在后端成功后更新页面；返回 `409` 时保留原表单和本地状态。
- 历史抽屉已打开时，成功保存后刷新版本列表和 `current_version`。
- 删除历史入口先取墓碑列表，再以其中的 `order_uid` 复用同一历史抽屉。
- 不提供恢复、编辑或删除历史的按钮。
- 订单列表搜索不匹配历史旧原单号或转单号。

### 2.9 角色编辑权限

`edit_policy` 的布尔字段直接对应前端控件：

| 字段 | 控件范围 |
| --- | --- |
| `order_fields` | 订单非重量字段 |
| `order_weight` | 订单重量 |
| `salesman` | 业务员选择 |
| `customer_assignment` | 客户归属 |
| `cargo_content` / `cargo_weight` | 普通货物内容 / 重量 |
| `box_content` / `box_weight` | 箱内容 / 重量 |
| `tracking_numbers` | `transfer_id`、`waybill_id` |
| `box_workers` | 箱子操作员 |
| `box_membership` | 新增、移除、分配、解绑箱子 |
| `archive_or_delete` | 归档和删除 |

上述权限按角色计算，不再叠加订单锁或收据历史约束。详情不再返回 `receipt_locked`、`receipt_lock`、`business_lock`、`financial_lock`、`lock_warnings`，编辑策略不再包含锁定、修订或财务锁字段。

`clerk` 计入箱子编辑角色，可编辑箱子内容、原单号、转单号和操作员；称重权限仍单独由 `box_weight` 控制。

订单列表执行归档后，后端会在同一事务内归档关联货物/箱子及订单所属财务信息。前端无需再逐项调用箱子或财务接口；收款单和订单历史仍作为审计记录保留。

### 2.10 箱内容、操作员和单号

`PUT /api/box/<uid>` 可原子提交箱内容与 `worker_ids`：

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

未传 `worker_ids` 表示保留，空数组表示清空，最多 4 个操作员。新页面应使用该原子保存入口；旧操作员接口仅作兼容。

字段标签统一为：

- `transfer_id`：原单号。
- `waybill_id`：转单号（运单号）。

箱子一旦出库，箱号和原单号固定，撤销出库后也不能修改。箱子响应 `identity_editable=false` 时这两个字段只读且保存时不提交，当前出库/后续状态也作只读兜底；转单号仍按角色权限编辑。装箱单操作栏允许管理员和店长通过 `POST /api/box/<uid>/undo-ship` 撤销出库，确认后刷新箱子列表；恢复待出库、清空转单号和出库时间，保留订单归属、原单号与历史记录。操作区每行两个按钮：第一行“编辑、撤销出库”，第二行“归档、删除”；归档带垃圾桶图标，删除无图标。

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

`transfer_id` 显示为“原单号”，`waybill_id` 显示为“转单号（运单号）”。

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

上传转运单文件，批量更新运单号并发货。

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
  "success_list": []
}
```

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

## 5. 日志模块 (Log)

### 5.1 获取操作日志

获取系统操作日志。

- **URL:** `GET /api/logs`
- **认证:** 需要
- **权限:** `admin`

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "time": "2026-03-26 15:00:00",
      "user": "admin",
      "action": "Create order.",
      "ip": "192.168.1.1"
    }
  ]
}
```

---

## 6. 差价补收

`GET /api/receivable-adjustments?status=pending&p=1&s=20` 返回待处理重报价差价；`GET /api/receivable-adjustments/<id>` 返回单条差价详情，供驳回收款单复制新建时获取最新余额。业务员只查看本人负责的报价，管理员、财务查看全部。

差价返回 `customer_id`、`approved_received`（关联该差价的审核通过实收）、`pending_amount`（关联待审金额）、`available_amount`（当前可补收金额）和 `collection_blocked_reason`（无法补收原因）。可补收金额同时受差价剩余金额和订单真实可收余额限制；退款差价、已有待审补收、未关联客户或无可收余额时禁止登记。

在待处理差价表点击「登记补收」，录入本次补收金额、收款日期、收款方式和备注，调用现有收款单接口：

```json
{
  "customer_id": 1,
  "receipt_date": "2026-09-30",
  "payment_method": "cash",
  "settlement_status": "unsettled",
  "remark": "补收重报价差价",
  "items": [{ "order_uid": "ORDER-UID", "amount": 20, "adjustment_id": 3 }]
}
```

`POST /api/receipts` 的明细可选 `adjustment_id`；关联差价的收款单只包含一笔明细并固定使用 `unsettled`，支持分次实收且不自动减免余款。提交后占用余额，财务审核通过才计入实收并更新差价处理状态；同一差价需先审核或驳回上一笔，再登记下一笔。驳回后释放占用，可保留差价关联复制新建。详情明细返回 `adjustment_id`。退款差价保留财务处理提示，不生成正数收款单。

### 6.1 订单详情收款与业务员筛选

订单详情加载报价历史后，在存在有效最终报价且登录人为管理员或该报价人时显示「收款」。点击后用 `GET /api/receivables/orders?order_uid=<uid>` 精确读取当前可收余额，复用收款管理的金额、日期、方式、结清状态和备注流程；提交 `POST /api/receipts` 后通过 `GET /api/receipts/<id>/pdf` 打开收据。没有普通可收余额时，使用 `GET /api/receivable-adjustments?order_uid=<uid>&status=pending` 查询可补收差价；两者均无可收余额时仅提示，不能提交收款。

管理员进入收款管理时，业务员筛选默认选择本人，可清空查看全部或切换其他业务员。筛选位于页签上方，适用于可收款订单、待处理差价及收款单记录。`owner_id` 在订单和差价列表按当前有效报价人筛选，在 `GET /api/receipts` 按收款单创建人筛选；管理员代登记的收据归创建该单的管理员。业务员的范围继续由服务端限制，传入他人的 `owner_id` 不会扩大权限。

## 7. 其他

### 7.1 获取客户端 IP

获取当前请求的客户端 IP 地址。

- **URL:** `GET /ip`
- **认证:** 不需要

**响应示例:**

```
192.168.1.1
```

---

## 手写装箱单

使用标准 `/api` 前缀，所有请求均发送系统的 `x-token`、`x-time` 认证头。

| 接口 | 用途 |
| --- | --- |
| `GET /api/intakes/template` | 下载 `application/pdf` 格式的 A4 空白装箱单，下载名 `paper-packing-list-a4.pdf`；有上传权限的用户可用 |
| `POST /api/intakes` | 上传 `multipart/form-data` 的 `photos`，后台自动识别；`mark_hint`、`note`、`operation_at` 可选 |
| `GET /api/intakes/my-packing-lists` | 本人手动创建的装箱单和上传纸单；支持 `page`、`page_size`、`mark`，不返回内部识别结果 |
| `GET /api/intakes?status=pending` | 审核员待核对纸单清单，支持 `page`、`page_size`、`mark` |
| `GET /api/intakes/:uid` | 审核详情及原图引用 |
| `GET /api/intakes/workers` | 审核员可选择的已批准实际操作人员，返回 `{id, name}` 数组 |
| `PUT /api/intakes/:uid/draft` | 保存 `{version, draft}`，草稿可不完整；`draft` 包含 `mark`、`operator_name`、`worker_ids`、`boxes` |
| `POST /api/intakes/:uid/recognize` | 审核员重试识别，发送 `{version}` |
| `POST /api/intakes/:uid/confirm` | 审核员确认生成正式装箱单，发送 `{version}`；至少绑定 1 名、最多 4 名实际工人 |

上传最多 8 张，每张不超过 10MB，合计不超过 24MB。`draft_is_manual` 标识已人工保存的草稿；客户端仅在尚无人工草稿且本地未编辑时自动填入识别结果。`operator_name` 是纸面署名提示，实际员工关系使用 `worker_ids`。工人通过正式 `/packing-list/new` 上传，并在 `/packing-lists` 查看个人记录；解析详情 `/intakes/:uid` 仅审核角色可访问。

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

## v1.6 发布协调

启用订单版本相关前端入口前，后端基线脚本应输出 `verified=True`。该字段表示 `orders == v1_coverage`；首次冻结发布还应满足 `orders == baseline_imports == v1_coverage`。其中 `baseline_imports` 只统计上线基线，`v1_coverage` 统计所有 V1（包括新订单的 `order_created`）。

---

*文档更新时间: 2026-09-16*
