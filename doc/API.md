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

## 6. 其他

### 6.1 获取客户端 IP

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
| `staff`         | 普通员工 | 基础业务操作                                  |

---

## 初始管理员账号

Docker 部署时通过环境变量配置初始管理员：

| 环境变量       | 默认值        | 说明           |
| -------------- | ------------- | -------------- |
| ADMIN_PHONE    | admin         | 管理员用户名   |
| ADMIN_PASSWORD | admin123      | 管理员密码     |
| ADMIN_NAME     | Administrator | 管理员显示名称 |

---

*文档生成时间: 2026-03-26*
