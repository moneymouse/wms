# WMS Backend API 接口文档 - v0.3 更新

**Base URL:** `http://localhost:5001`

**版本:** 0.3 (2026-04-03)

---

## 更新内容概述

本版本更新内容：

### 1. 订单-客户多对多关系

- 订单与客户之间由原来的弱引用（customer_name字符串）改为**多对多关系**
- 新增 `order_customers` 关联表
- 创建订单时**自动绑定客户关系**
- 订单数据中新增 `customer_ids` 字段

### 2. 客户接口参数变更

- 所有以 `customer_name` 为索引的接口**改为使用 `customer_id`**
- 提升查询效率，避免字符串匹配

---

## 订单模块变更

### 1. 创建订单（更新）

创建新订单，自动将当前用户设为负责人，**并自动绑定客户关系**。

- **URL:** `POST /api/create`
- **认证:** 需要

**请求参数:**

```json
{
  "order_id": "ORD20260403001",
  "customer_name": "客户A",
  "receiver": "收件人姓名",
  "receiver_phone": "13800138000",
  "address": "收件地址",
  "zip_code": "100000",
  "country": "中国",
  "tag_all": "标签",
  "cargo_count": 3
}
```

**行为变更:**

- 创建订单时，根据 `customer_name` 查找或创建客户
- 自动在 `order_customers` 表中建立订单与客户的关联关系

---

### 2. 获取订单（更新）

订单数据中新增 `customer_ids` 字段。

- **URL:** `GET /api/orders/<uid>`
- **认证:** 需要

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "uid": "abc123",
    "order_id": "ORD20260403001",
    "customer_name": "客户A",
    "customer_ids": [1],
    "salesman_id": 1,
    "salesman": {
      "id": 1,
      "name": "张三",
      "phone": "13800138000"
    },
    "cargo_uid_list": ["cargo1", "cargo2"]
  }
}
```

**字段说明:**

| 字段         | 类型       | 说明             |
| ------------ | ---------- | ---------------- |
| customer_ids | array[int] | 关联的客户ID列表 |

---

## 客户模块变更

### ⚠️ 重要变更：所有接口参数由 `customer_name` 改为 `customer_id`

---

### 1. 获取客户列表

获取所有客户列表。

- **URL:** `GET /api/customer_list`
- **认证:** 需要

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {"id": 1, "name": "客户A"},
    {"id": 2, "name": "客户B"}
  ]
}
```

---

### 2. 获取客户名下的收件人列表（⚠️ 参数变更）

- **原URL:** `GET /api/receiver_list/<customer_name>`
- **新URL:** `GET /api/receiver_list/<customer_id>`
- **认证:** 需要

**路径参数:**

| 参数        | 类型 | 说明   |
| ----------- | ---- | ------ |
| customer_id | int  | 客户ID |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {"receiver_id": "1", "receiver_name": "收件人A"},
    {"receiver_id": "2", "receiver_name": "收件人B"}
  ]
}
```

---

### 3. 获取客户名下收件人完整信息列表（⚠️ 参数变更）

- **原URL:** `GET /api/receiver_info_list/<customer_name>`
- **新URL:** `GET /api/receiver_info_list/<customer_id>`
- **认证:** 需要

**路径参数:**

| 参数        | 类型 | 说明   |
| ----------- | ---- | ------ |
| customer_id | int  | 客户ID |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "receiver_id": "1",
      "receiver": "收件人A",
      "receiver_phone": "13800138001",
      "mail": "a@example.com",
      "country": "中国",
      "province": "广东",
      "city": "深圳",
      "address": "某某路1号",
      "zip_code": "518000"
    }
  ]
}
```

---

### 4. 删除收件人（⚠️ 参数变更）

- **原URL:** `POST /api/del/<customer_name>/<receiver_id>`
- **新URL:** `POST /api/del/<customer_id>/<receiver_id>`
- **认证:** 需要

**路径参数:**

| 参数        | 类型   | 说明     |
| ----------- | ------ | -------- |
| customer_id | int    | 客户ID   |
| receiver_id | string | 收件人ID |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

---

### 5. 删除客户（⚠️ 参数变更）

删除客户及其所有收件人记录。

- **原URL:** `POST /api/del_customer/<customer_name>`
- **新URL:** `POST /api/del_customer/<customer_id>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`
- **审计日志:** ✓ 会记录删除日志

**路径参数:**

| 参数        | 类型 | 说明   |
| ----------- | ---- | ------ |
| customer_id | int  | 客户ID |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success"
}
```

**错误响应:**

| code | msg      |
| ---- | -------- |
| 403  | 权限不足 |

---

### 6. 获取单个客户详细信息（⚠️ 参数变更）

获取指定客户的详细信息，包括phone和wechat等敏感字段。

- **原URL:** `GET /api/customer_detail/<customer_name>`
- **新URL:** `GET /api/customer_detail/<customer_id>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`
- **审计日志:** ✓ 会记录访问日志

**路径参数:**

| 参数        | 类型 | 说明   |
| ----------- | ---- | ------ |
| customer_id | int  | 客户ID |

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

---

### 7. 更新客户联系信息（⚠️ 参数变更）

更新客户的phone和wechat信息。

- **原URL:** `POST /api/customer_info/<customer_name>`
- **新URL:** `POST /api/customer_info/<customer_id>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`
- **审计日志:** ✓ 会记录修改日志

**路径参数:**

| 参数        | 类型 | 说明   |
| ----------- | ---- | ------ |
| customer_id | int  | 客户ID |

**请求参数:**

```json
{
  "phone": "13912345678",
  "wechat": "wx_new_wechat"
}
```

**响应示例:**

```json
{
  "code": 200,
  "msg": "Customer info updated successfully"
}
```

**注意:** 与v0.2版本不同，如果客户不存在将不再自动创建，而是直接返回（无操作）。

---

## 数据库变更

### 新增表: order_customers

订单与客户的多对多关联表。

| 字段        | 类型        | 说明                          |
| ----------- | ----------- | ----------------------------- |
| order_uid   | VARCHAR(32) | 订单UID，外键关联 orders.uid  |
| customer_id | INT         | 客户ID，外键关联 customers.id |

**联合主键:** (order_uid, customer_id)

**迁移文件:**
- Alembic: `alembic/versions/20260403_0002_add_order_customers_association.py`
- SQL: `migrations/002_add_order_customers_association.sql`

---

## API 变更汇总

| 原接口                                        | 新接口                                      |
| --------------------------------------------- | ------------------------------------------- |
| `GET /api/receiver_list/<customer_name>`      | `GET /api/receiver_list/<customer_id>`      |
| `GET /api/receiver_info_list/<customer_name>` | `GET /api/receiver_info_list/<customer_id>` |
| `POST /api/del/<customer_name>/<receiver_id>` | `POST /api/del/<customer_id>/<receiver_id>` |
| `POST /api/del_customer/<customer_name>`      | `POST /api/del_customer/<customer_id>`      |
| `GET /api/customer_detail/<customer_name>`    | `GET /api/customer_detail/<customer_id>`    |
| `POST /api/customer_info/<customer_name>`     | `POST /api/customer_info/<customer_id>`     |

---

*文档生成时间: 2026-04-03*
