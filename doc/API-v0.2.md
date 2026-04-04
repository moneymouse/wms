# WMS Backend API 接口文档 - v0.1 更新

**Base URL:** `http://localhost:5001`

**版本:** 0.1 (2026-04-03)

### 4.9 获取单个客户详细信息（含敏感字段）

获取单个客户的详细信息，包括phone和wechat等敏感字段。

- **URL:** `GET /api/customer_detail/<customer_id>`
- **认证:** 需要
- **权限:** `admin`（管理员）、`store_manager`（店长）、`salesperson`（业务员）
- **审计日志:** ✓ 会记录访问日志

**路径参数:**

| 参数        | 类型 | 说明           |
| ----------- | ---- | -------------- |
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

| code | msg                |
| ---- | ------------------ |
| 401  | 未登录或token无效  |
| 403  | 权限不足           |
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

| 参数   | 类型   | 必填 | 说明       |
| ------ | ------ | ---- | ---------- |
| phone  | string | 否   | 客户电话   |
| wechat | string | 否   | 客户微信号 |

**响应示例:**

```json
{
  "code": 200,
  "msg": "Customer info updated successfully"
}
```

**错误响应:**

| code | msg                                 |
| ---- | ----------------------------------- |
| 401  | 未登录或token无效                   |
| 403  | 权限不足                            |
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

---