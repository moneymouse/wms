# WMS Backend API 接口文档

**Base URL:** `http://localhost:5001`

**版本:** 1.0

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
  "remark": "备注信息"
}
```

**响应示例:**

```json
{
  "code": 200,
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
    "cargo_uid_list": ["cargo1", "cargo2", "cargo3"]
  }
}
```

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

获取所有订单下货物的转运号和运单号。

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

### 4.8 获取所有客户详细信息（含敏感字段）

获取所有客户的详细信息，包括phone和wechat等敏感字段。

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

响应增加 `weight_snapshot`、`current_weight`、`receivable_amount`、`effective_date`、`is_effective` 和 `validity_status`。`receivable_amount` 按 `round(weight_snapshot × unit_price + surcharge, 2)` 计算。低于渠道 `min_price` 的每公斤单价进入 `pending`，附加费不参与最低报价判断。

`validity_status` 取值：`effective`、`pending`、`rejected`、`superseded`、`stale`。订单当前未归档包裹总重与快照相差 0.001kg 或以上时为 `stale`，必须重新报价。

- **待审核报价:** `GET /api/finance/quote-approvals`，权限为 `admin`
- **审核:** `PUT /api/finance/quote-approvals/<quote_id>`，请求体为 `{ "action": "approve|reject", "review_remark": "..." }`
- **双语报价单:** `GET /api/orders/<uid>/quote-pdf`

新报价应收低于该订单已审核收款与待审核占用之和时返回 `409`。

### 7.2 可收款订单与收款单

- **可收款订单:** `GET /api/receivables/orders?customer_id=<id>&q=<订单号>`，权限为 `salesperson`、`admin`
- **创建收款单:** `POST /api/receipts`，权限为 `salesperson`、`admin`
- **收款单列表:** `GET /api/receipts?p=1&s=20&status=pending&q=<单号或客户>`
- **收款单详情:** `GET /api/receipts/<id>`
- **双语 PDF:** `GET /api/receipts/<id>/pdf`

```json
{
  "customer_id": 1,
  "receipt_date": "2026-08-27",
  "payment_method": "bank_transfer",
  "remark": "首笔部分收款",
  "items": [
    { "order_uid": "ORDER-UID", "amount": 80 }
  ]
}
```

`payment_method` 可取 `cash`、`bank_transfer`、`wechat`、`alipay`、`other`。一张收款单只能包含一个客户的订单；业务员只能登记当前有效报价人为本人的订单，管理员可代登记。待审核金额立即占用可收余额，金额必须大于 0 且不能超额。单号格式为 `RCPT-YYYYMMDD-xxxxxx`。

状态为 `pending`、`approved`、`rejected`。三种状态均可打印，PDF 响应为 Base64 编码，字段 `mime_type` 为 `application/pdf`。

### 7.3 收款审核

- **URL:** `PUT /api/finance/receipts/<id>/review`
- **权限:** `finance`、`admin`
- **请求:** `{ "action": "approve|reject", "review_remark": "..." }`

创建人不能审核自己的收款单。驳回必须填写审核意见；驳回单永久保留，原待审核占用自动释放。只有 `approved` 明细计入已收账款。

### 7.4 应收账款台账

- **URL:** `GET /api/finance/accounts-receivable`
- **权限:** `finance`、`admin`
- **参数:** `as_of=YYYY-MM-DD`、`customer_id`、`owner_id`、`status=unpaid|partial|paid`、`q`、`p`、`s`

响应 `data.items` 按订单返回负责人、报价生效日、报价重量、应收、已收、未收、待审核占用与结清状态；`data.totals` 返回当前筛选结果的合计。历史口径按报价 `effective_date` 和收款 `review_date` 截止到查询日 23:59:59 计算。

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

*文档更新时间: 2026-08-27*
