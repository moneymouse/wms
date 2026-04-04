# WMS Backend API 接口文档 - v0.4 更新

**Base URL:** `http://localhost:5001`

**版本:** 0.4 (2026-04-04)

---

## 更新内容概述

本版本更新内容：

### 1. 客户管理接口

- 新增 `POST /api/customer` 创建客户接口
- 新增 `PUT /api/customer/<customer_id>` 修改客户接口
- 客户创建与订单创建解耦，需先创建客户再创建订单

### 2. 订单创建流程变更

- 创建订单时不再自动创建客户
- 如果 `customer_name` 对应的客户不存在，返回 404 错误
- 收件人信息仍自动添加到客户名下

---

## 客户模块

### 1. 创建客户（新增）

创建客户基本信息。

- **URL:** `POST /api/customer`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`
- **审计日志:** ✓ 会记录创建日志

**请求参数:**

```json
{
  "name": "客户名称",
  "phone": "13800138000",
  "wechat": "wx_customer"
}
```

| 参数   | 类型   | 必填 | 说明     |
| ------ | ------ | ---- | -------- |
| name   | string | 是   | 客户名称 |
| phone  | string | 否   | 客户电话 |
| wechat | string | 否   | 客户微信 |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "customer_id": 1
  }
}
```

**错误响应:**

| code | msg                     |
| ---- | ----------------------- |
| 400  | name is required        |
| 400  | Customer already exists |
| 403  | 权限不足                |

---

### 2. 修改客户信息（新增）

修改客户基本信息。

- **URL:** `PUT /api/customer/<customer_id>`
- **认证:** 需要

**路径参数:**

| 参数        | 类型 | 说明   |
| ----------- | ---- | ------ |
| customer_id | int  | 客户ID |

**请求参数:**

```json
{
  "name": "新客户名称",
  "phone": "13900139000",
  "wechat": "wx_new"
}
```

| 参数   | 类型   | 必填 | 说明                       |
| ------ | ------ | ---- | -------------------------- |
| name   | string | 否   | 新客户名称                 |
| phone  | string | 否   | 客户电话（空字符串则清空） |
| wechat | string | 否   | 客户微信（空字符串则清空） |

**响应示例:**

```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "id": 1,
    "name": "新客户名称",
    "phone": "13900139000",
    "wechat": "wx_new"
  }
}
```

**错误响应:**

| code | msg                          |
| ---- | ---------------------------- |
| 404  | Customer not found           |
| 400  | Customer name already exists |

---

## 订单模块变更

### 1. 创建订单（更新）

创建新订单。**客户必须先存在**，否则返回 404 错误。

- **URL:** `POST /api/create`
- **认证:** 需要

**请求参数:**

```json
{
  "order_id": "ORD20260404001",
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

**行为说明:**

- 根据 `customer_name` 查找已存在的客户
- 如果客户不存在，返回 404 错误（**不再自动创建**）
- 自动将收件人信息添加到客户名下
- 自动在 `order_customers` 表中建立订单与客户的关联关系

**错误响应:**

| code | msg                      |
| ---- | ------------------------ |
| 404  | Customer 'xxx' not found |
| 500  | Record Existed           |

---

## 使用流程示例

```
# 1. 先创建客户
POST /api/customer
{
  "name": "客户A",
  "phone": "13800138000",
  "wechat": "wx_customer_a"
}
→ { "code": 200, "data": { "customer_id": 1 } }

# 2. 创建订单（客户必须已存在）
POST /api/create
{
  "order_id": "ORD001",
  "customer_name": "客户A",
  "receiver": "张三",
  "address": "北京市xxx"
}
→ { "code": 200, "msg": "success" }

# 3. 如需修改客户信息
PUT /api/customer/1
{
  "phone": "13900139000"
}
→ { "code": 200, "data": { "id": 1, "name": "客户A", "phone": "13900139000", ... } }
```

---

## API 变更汇总

| 接口                              | 变更类型 | 说明                              |
| --------------------------------- | -------- | --------------------------------- |
| `POST /api/customer`              | 新增     | 创建客户                          |
| `PUT /api/customer/<customer_id>` | 新增     | 修改客户信息                      |
| `POST /api/create`                | 修改     | 客户不存在时返回404，不再自动创建 |

---

*文档生成时间: 2026-04-04*
