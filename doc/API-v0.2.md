# WMS Backend API 接口文档 - v0.1 更新

**Base URL:** `http://localhost:5001`

**版本:** 0.1 (2026-04-03)

### 4.9 获取单个客户详细信息（含敏感字段）

获取指定客户的详细信息，包括phone和wechat等敏感字段。

- **URL:** `GET /api/customer_detail/<customer_name>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`
- **审计日志:** ✓ 会记录访问日志

**路径参数:**

| 参数          | 类型   | 说明     |
| ------------- | ------ | -------- |
| customer_name | string | 客户名称 |

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
| 404  | 客户不存在        |

---

### 4.10 更新客户联系信息

更新客户的phone和wechat信息。如果客户不存在，会自动创建。

- **URL:** `POST /api/customer_info/<customer_name>`
- **认证:** 需要
- **权限:** `admin`、`store_manager`、`salesperson`
- **审计日志:** ✓ 会记录修改日志

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

| 参数   | 类型   | 必填 | 说明                             |
| ------ | ------ | ---- | -------------------------------- |
| phone  | string | 否   | 客户电话（可选，传空字符串清空） |
| wechat | string | 否   | 客户微信（可选，传空字符串清空） |

**响应示例:**

```json
{
  "code": 200,
  "msg": "Customer info updated successfully"
}
```

**错误响应:**

| code | msg                        |
| ---- | -------------------------- |
| 401  | 未登录或token无效          |
| 403  | 权限不足                   |
| 500  | 服务器错误（如数据库异常） |

**说明:**
- `phone`和`wechat`都是可选的，可以只更新其中一个
- 如果客户不存在，会自动创建新客户记录
- 传入空字符串（`""`）会清空对应字段
- 传入`null`或不传该字段则不更新对应字段

---

## 5. 日志模块 (Log)

### 5.1 获取操作日志

获取系统操作日志。

- **URL:** `GET /api/logs`
- **认证:** 需要
- **权限:** `admin`
- **说明:** 返回日志时会一并包含发起操作的用户姓名和角色，便于在日志页面直接识别操作者。

**响应示例:**

```json
{
  "code": 200,
  "data": [
    {
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

---
