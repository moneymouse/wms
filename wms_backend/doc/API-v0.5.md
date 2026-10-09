# WMS Backend API 接口文档 - v0.5 更新

**Base URL:** `http://localhost:5001`

**版本:** 0.5 (2026-04-05)

---

## 更新内容概述

本版本新增入库流程功能，包括：

### 1. 装箱单模块（新增）
- `POST /api/packing-list` 创建装箱单
- `GET /api/packing-lists` 获取装箱单列表
- `GET /api/packing-list/<uid>` 获取装箱单详情
- `PUT /api/packing-list/<uid>` 更新装箱单
- `DELETE /api/packing-list/<uid>` 删除装箱单
- `POST /api/packing-list/<uid>/complete` 完成装箱单

### 2. 箱子模块（新增）
- `POST /api/packing-list/<list_uid>/box` 添加箱子
- `GET /api/box/<uid>` 获取箱子详情
- `PUT /api/box/<uid>` 更新箱子
- `PUT /api/box/<uid>/weigh` 称重
- `DELETE /api/box/<uid>` 删除箱子
- `PUT /api/box/<uid>/workers` 设置打包工人
- `GET /api/box/<uid>/workers` 获取打包工人
- `GET /api/box/<uid>/label` 获取箱子标签

### 3. 箱子分配模块（新增）
- `GET /api/customer/<customer_id>/boxes/unassigned` 获取未分配箱子
- `POST /api/boxes/assign` 批量分配箱子到订单

### 4. 照片上传（新增）
- `POST /api/upload/photo` 上传照片

### 5. 新增角色
- `worker` 工人角色，用于仓库打包人员

---

## 装箱单模块

### 1. 创建装箱单

创建新的装箱单，自动生成唛头编号（格式：客户名-月日-3位序号）。

- **URL:** `POST /api/packing-list`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`
- **审计日志:** ✓

**请求参数:**

```json
{
  "customer_id": 1,
  "photos": ["/static/uploads/photos/xxx.jpg"]
}
```

| 参数        | 类型     | 必填 | 说明        |
| ----------- | -------- | ---- | ----------- |
| customer_id | int      | 是   | 客户ID      |
| photos      | string[] | 否   | 照片URL数组 |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "uid": "174624580000012",
    "list_number": "张三-0405-001",
    "customer_id": 1,
    "customer_name": "张三"
  }
}
```

**错误响应:**

| code | msg                     |
| ---- | ----------------------- |
| 400  | customer_id is required |
| 404  | Customer X not found    |
| 403  | Permission denied       |

---

### 2. 获取装箱单列表

分页获取装箱单列表，支持筛选和搜索。

- **URL:** `GET /api/packing-lists`
- **认证:** 需要

**查询参数:**

| 参数        | 类型   | 说明                           |
| ----------- | ------ | ------------------------------ |
| p           | int    | 页码，默认 1                   |
| s           | int    | 每页数量，默认 20              |
| customer_id | int    | 按客户筛选                     |
| status      | string | 按状态筛选（draft/completed）  |
| q           | string | 搜索关键词（唛头编号或客户名） |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "items": [
      {
        "uid": "174624580000012",
        "list_number": "张三-0405-001",
        "customer_id": 1,
        "customer_name": "张三",
        "photos": ["/static/uploads/photos/xxx.jpg"],
        "creator_id": 1,
        "creator_name": "admin",
        "status": "draft",
        "create_date": "2026-04-05 10:00",
        "boxes": [
          {
            "uid": "174624580000034",
            "item_name": "电子产品",
            "weight": 5.5,
            "status": "pending"
          }
        ]
      }
    ],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

---

### 3. 获取装箱单详情

- **URL:** `GET /api/packing-list/<uid>`
- **认证:** 需要

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "uid": "174624580000012",
    "list_number": "张三-0405-001",
    "customer_id": 1,
    "customer_name": "张三",
    "photos": ["/static/uploads/photos/xxx.jpg"],
    "creator_id": 1,
    "creator_name": "admin",
    "status": "draft",
    "create_date": "2026-04-05 10:00",
    "update_date": null,
    "boxes": [...]
  }
}
```

---

### 4. 更新装箱单

- **URL:** `PUT /api/packing-list/<uid>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`

**请求参数:**

```json
{
  "photos": [...],
  "status": "completed"
}
```

---

### 5. 删除装箱单

- **URL:** `DELETE /api/packing-list/<uid>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`

---

### 6. 完成装箱单

将装箱单状态设为已完成。

- **URL:** `POST /api/packing-list/<uid>/complete`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`

---

## 箱子模块

### 1. 添加箱子

为装箱单添加箱子。

- **URL:** `POST /api/packing-list/<list_uid>/box`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`

**请求参数:**

```json
{
  "item_name": "电子产品",
  "weight": 5.5
}
```

| 参数      | 类型   | 必填 | 说明                     |
| --------- | ------ | ---- | ------------------------ |
| item_name | string | 否   | 品名                     |
| weight    | float  | 否   | 重量(kg)，不填表示未称重 |

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "uid": "174624580000034",
    "packing_list_uid": "174624580000012",
    "item_name": "电子产品",
    "weight": 5.5,
    "status": "pending"
  }
}
```

---

### 2. 获取箱子详情

- **URL:** `GET /api/box/<uid>`
- **认证:** 需要

---

### 3. 更新箱子信息

- **URL:** `PUT /api/box/<uid>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`

**请求参数:**

```json
{
  "item_name": "新品名",
  "weight": 6.0
}
```

---

### 4. 称重箱子

专门用于称重操作。

- **URL:** `PUT /api/box/<uid>/weigh`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`

**请求参数:**

```json
{
  "weight": 5.5
}
```

**错误响应:**

| code | msg                           |
| ---- | ----------------------------- |
| 400  | weight must be greater than 0 |

---

### 5. 删除箱子

- **URL:** `DELETE /api/box/<uid>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`

---

### 6. 设置箱子打包工人

每个箱子最多关联4个打包工人，用于后续工人计薪功能。

- **URL:** `PUT /api/box/<uid>/workers`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`

**请求参数:**

```json
{
  "worker_ids": [1, 2, 3]
}
```

**错误响应:**

| code | msg                               |
| ---- | --------------------------------- |
| 400  | Maximum 4 workers allowed per box |

---

### 7. 获取箱子打包工人

- **URL:** `GET /api/box/<uid>/workers`
- **认证:** 需要

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "worker_id": 1,
      "worker_name": "工人A",
      "create_date": "2026-04-05 10:00"
    }
  ]
}
```

---

### 8. 获取箱子标签

获取箱子标签信息，用于打印。

- **URL:** `GET /api/box/<uid>/label`
- **认证:** 需要

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "uid": "174624580000034",
    "list_number": "张三-0405-001",
    "item_name": "电子产品",
    "weight": 5.5,
    "customer_name": "张三"
  }
}
```

---

## 箱子分配模块

### 1. 获取客户未分配的箱子

获取指定客户所有未分配的有效箱子，按唛头（装箱单编号）分组。

**注意:** 只有已称重（weight > 0）的箱子才是有效箱子，才能被分配。

- **URL:** `GET /api/customer/<customer_id>/boxes/unassigned`
- **认证:** 需要

**查询参数:**

| 参数       | 类型   | 说明                            |
| ---------- | ------ | ------------------------------- |
| valid_only | string | 是否只返回有效箱子，默认 "true" |

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
      "list_number": "张三-0405-001",
      "packing_list_uid": "174624580000012",
      "boxes": [
        {
          "uid": "174624580000034",
          "item_name": "电子产品",
          "weight": 5.5,
          "status": "pending"
        }
      ]
    }
  ]
}
```

---

### 2. 批量分配箱子到订单

将选中的箱子分配到指定订单。

- **URL:** `POST /api/boxes/assign`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`
- **审计日志:** ✓

**请求参数:**

```json
{
  "box_uids": ["uid1", "uid2", "uid3"],
  "order_uid": "订单UID"
}
```

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "success": ["uid1", "uid2"],
    "failed": [
      {
        "uid": "uid3",
        "error": "Box uid3 is already assigned"
      }
    ]
  }
}
```

---

## 照片上传

### 上传照片

- **URL:** `POST /api/upload/photo`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`、`worker`
- **Content-Type:** `multipart/form-data`

**请求参数:**

| 参数  | 类型 | 说明     |
| ----- | ---- | -------- |
| photo | file | 照片文件 |

**支持的格式:** png, jpg, jpeg, gif, webp

**响应示例:**

```json
{
  "code": 200,
  "data": {
    "url": "/static/uploads/photos/1746245800000_abc123.jpg"
  }
}
```

---

## 新增角色说明

### worker（工人）

用于仓库打包人员，具有以下权限：

| 功能       | 权限 |
| ---------- | ---- |
| 创建装箱单 | ✓    |
| 查看装箱单 | ✓    |
| 添加箱子   | ✓    |
| 称重       | ✓    |
| 设置工人   | ✓    |
| 分配箱子   | ✗    |
| 删除箱子   | ✗    |
| 删除装箱单 | ✗    |

---

## 数据库变更

### 新增表

#### packing_lists（装箱单）

| 字段        | 类型        | 说明                          |
| ----------- | ----------- | ----------------------------- |
| uid         | VARCHAR(32) | 主键                          |
| list_number | VARCHAR(64) | 唛头编号（唯一）              |
| customer_id | INT         | 客户ID（外键 → customers.id） |
| photos      | TEXT        | 照片路径，JSON数组            |
| creator_id  | INT         | 创建人ID（外键 → users.id）   |
| status      | VARCHAR(32) | 状态：draft/completed         |
| create_date | VARCHAR(32) | 创建时间                      |
| update_date | VARCHAR(32) | 更新时间                      |
| archive     | TINYINT(1)  | 软删除标记                    |

#### boxes（箱子）

| 字段             | 类型         | 说明                         |
| ---------------- | ------------ | ---------------------------- |
| uid              | VARCHAR(32)  | 主键                         |
| packing_list_uid | VARCHAR(32)  | 所属装箱单（外键）           |
| item_name        | VARCHAR(256) | 品名                         |
| weight           | FLOAT        | 重量(kg)，NULL表示未称重     |
| target_order_uid | VARCHAR(32)  | 分配到的订单（外键，可为空） |
| status           | VARCHAR(32)  | 状态：pending/assigned       |
| create_date      | VARCHAR(32)  | 创建时间                     |
| update_date      | VARCHAR(32)  | 更新时间                     |
| archive          | TINYINT(1)   | 软删除标记                   |

#### box_workers（箱子-工人关联）

| 字段        | 类型        | 说明                       |
| ----------- | ----------- | -------------------------- |
| id          | INT         | 主键自增                   |
| box_uid     | VARCHAR(32) | 箱子ID（外键 → boxes.uid） |
| worker_id   | INT         | 工人ID（外键 → users.id）  |
| create_date | VARCHAR(32) | 记录时间                   |

---

## 使用流程示例

```
# 1. 工人创建装箱单
POST /api/packing-list
{
  "customer_id": 1
}
→ { "code": 200, "data": { "uid": "xxx", "list_number": "张三-0405-001" } }

# 2. 上传照片（可选）
POST /api/upload/photo
(multipart/form-data with photo file)
→ { "code": 200, "data": { "url": "/static/uploads/photos/xxx.jpg" } }

# 3. 添加箱子
POST /api/packing-list/xxx/box
{
  "item_name": "电子产品"
}
→ { "code": 200, "data": { "uid": "yyy", ... } }

# 4. 称重
PUT /api/box/yyy/weigh
{
  "weight": 5.5
}
→ { "code": 200, "msg": "success" }

# 5. 设置打包工人
PUT /api/box/yyy/workers
{
  "worker_ids": [1, 2]
}
→ { "code": 200, "msg": "success" }

# 6. 完成装箱单
POST /api/packing-list/xxx/complete
→ { "code": 200, "msg": "success" }

# 7. 业务员在订单详情页分配箱子
GET /api/customer/1/boxes/unassigned
→ { "code": 200, "data": [{ "list_number": "张三-0405-001", "boxes": [...] }] }

POST /api/boxes/assign
{
  "box_uids": ["yyy"],
  "order_uid": "订单UID"
}
→ { "code": 200, "data": { "success": ["yyy"], "failed": [] } }
```

---

## API 变更汇总

| 接口                                      | 变更类型 | 说明           |
| ----------------------------------------- | -------- | -------------- |
| `POST /api/packing-list`                  | 新增     | 创建装箱单     |
| `GET /api/packing-lists`                  | 新增     | 获取装箱单列表 |
| `GET /api/packing-list/<uid>`             | 新增     | 获取装箱单详情 |
| `PUT /api/packing-list/<uid>`             | 新增     | 更新装箱单     |
| `DELETE /api/packing-list/<uid>`          | 新增     | 删除装箱单     |
| `POST /api/packing-list/<uid>/complete`   | 新增     | 完成装箱单     |
| `POST /api/packing-list/<list_uid>/box`   | 新增     | 添加箱子       |
| `GET /api/box/<uid>`                      | 新增     | 获取箱子详情   |
| `PUT /api/box/<uid>`                      | 新增     | 更新箱子       |
| `PUT /api/box/<uid>/weigh`                | 新增     | 称重           |
| `DELETE /api/box/<uid>`                   | 新增     | 删除箱子       |
| `PUT /api/box/<uid>/workers`              | 新增     | 设置打包工人   |
| `GET /api/box/<uid>/workers`              | 新增     | 获取打包工人   |
| `GET /api/box/<uid>/label`                | 新增     | 获取箱子标签   |
| `GET /api/customer/<id>/boxes/unassigned` | 新增     | 获取未分配箱子 |
| `POST /api/boxes/assign`                  | 新增     | 批量分配箱子   |
| `POST /api/upload/photo`                  | 新增     | 上传照片       |

---

*文档生成时间: 2026-04-05*
