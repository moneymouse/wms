# WMS Backend API 接口文档 - v0.6 更新

**Base URL:** `http://localhost:5001`

**版本:** 0.6 (2026-04-05)

---

## 更新内容概述

本版本新增密码管理功能，包括：

### 1. 忘记密码申请（新增）
- `POST /api/auth/password/forgot` 提交忘记密码申请（需管理员审核）

### 2. 修改密码（新增）
- `POST /api/auth/password/change` 登录用户修改密码

### 3. 密码重置申请管理（新增）
- `GET /api/auth/password/requests` 获取待审核的密码重置申请
- `POST /api/auth/password/approve/<request_id>` 审核通过密码重置申请
- `POST /api/auth/password/reject/<request_id>` 拒绝密码重置申请

### 4. 管理员重置密码（新增）
- `POST /api/users/<user_id>/reset-password` 管理员直接重置用户密码

### 5. 新增数据表
- `password_reset_requests` 密码重置申请表

---

## 密码管理模块

### 1. 忘记密码申请

用户忘记密码时，提交新密码等待管理员审核。

- **URL:** `POST /api/auth/password/forgot`
- **认证:** 不需要
- **权限:** 无

**请求体:**
```json
{
    "phone": "13800138000",
    "new_password": "newpassword123"
}
```

**成功响应 (200):**
```json
{
    "code": 200,
    "msg": "申请已提交，请等待管理员审核"
}
```

**错误响应:**
- `400`: 手机号和新密码不能为空 / 密码长度不能少于6位
- `404`: 该手机号未注册

---

### 2. 登录用户修改密码

已登录用户修改自己的密码，需要验证旧密码。

- **URL:** `POST /api/auth/password/change`
- **认证:** 需要（通过 x-token）
- **权限:** 已登录用户

**请求头:**
```
x-token: <JWT_TOKEN>
```

**请求体:**
```json
{
    "old_password": "oldpassword",
    "new_password": "newpassword123"
}
```

**成功响应 (200):**
```json
{
    "code": 200,
    "msg": "密码修改成功"
}
```

**错误响应:**
- `400`: 旧密码和新密码不能为空 / 新密码长度不能少于6位
- `401`: 旧密码错误

---

### 3. 获取待审核的密码重置申请

获取所有待审核的密码重置申请列表。

- **URL:** `GET /api/auth/password/requests`
- **认证:** 需要
- **权限:** admin

**请求头:**
```
x-token: <JWT_TOKEN>
```

**成功响应 (200):**
```json
{
    "code": 200,
    "data": [
        {
            "id": 1,
            "user_id": 5,
            "user_name": "张三",
            "user_phone": "13800138000",
            "status": "pending",
            "create_date": "2026-04-05 16:00"
        }
    ]
}
```

---

### 4. 审核通过密码重置申请

管理员审核通过密码重置申请，用户密码将被更新为申请时提交的新密码。

- **URL:** `POST /api/auth/password/approve/<request_id>`
- **认证:** 需要
- **权限:** admin

**请求头:**
```
x-token: <JWT_TOKEN>
```

**成功响应 (200):**
```json
{
    "code": 200,
    "msg": "已通过，用户密码已更新"
}
```

**错误响应:**
- `404`: 申请不存在或已被处理

---

### 5. 拒绝密码重置申请

管理员拒绝密码重置申请。

- **URL:** `POST /api/auth/password/reject/<request_id>`
- **认证:** 需要
- **权限:** admin

**请求头:**
```
x-token: <JWT_TOKEN>
```

**请求体:**
```json
{
    "remark": "拒绝原因（选填）"
}
```

**成功响应 (200):**
```json
{
    "code": 200,
    "msg": "已拒绝"
}
```

**错误响应:**
- `404`: 申请不存在或已被处理

---

### 6. 管理员直接重置用户密码

管理员可以直接为指定用户设置新密码，无需用户申请。

- **URL:** `POST /api/users/<user_id>/reset-password`
- **认证:** 需要
- **权限:** admin

**请求头:**
```
x-token: <JWT_TOKEN>
```

**请求体:**
```json
{
    "new_password": "newpassword123"
}
```

**成功响应 (200):**
```json
{
    "code": 200,
    "msg": "密码已重置"
}
```

**错误响应:**
- `400`: 新密码不能为空 / 密码长度不能少于6位
- `404`: 用户不存在

---

## 数据库更新

### 新增表: password_reset_requests

| 字段              | 类型         | 说明                            |
| ----------------- | ------------ | ------------------------------- |
| id                | INTEGER      | 主键，自增                      |
| user_id           | INTEGER      | 关联用户ID (外键 -> users.id)   |
| new_password_hash | VARCHAR(512) | 新密码哈希值                    |
| status            | ENUM         | 状态：pending/approved/rejected |
| remark            | VARCHAR(256) | 备注（拒绝原因等）              |
| create_date       | VARCHAR(32)  | 申请时间                        |
| update_date       | VARCHAR(32)  | 处理时间                        |

迁移脚本: `migrations/005_add_password_reset_requests.sql`

---

## 前端新增页面

### 1. 忘记密码页面
- **路径:** `/forget_password`
- **功能:** 用户输入手机号和新密码，提交后等待管理员审核

### 2. 设置页面
- **路径:** `/settings`
- **功能:** 登录用户修改密码
- **权限:** 所有已登录用户

### 3. 管理员页面增强
- **路径:** `/admin`
- **新增功能:**
  - 密码重置申请审核表格
  - 用户列表中的"重置密码"按钮
