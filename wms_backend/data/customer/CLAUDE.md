# Customer 客户模块

## 功能概述
客户模块负责管理客户信息和收货人信息，是仓库管理系统中处理客户关系的核心模块。

## 数据模型

### CustomerTable
客户表，存储客户基本信息和敏感联系方式：
- `id`: Integer - 客户唯一标识（主键，自增）
- `name`: String(256) - 客户名称（唯一，非空）
- `phone`: String(64) - **客户联系电话（敏感字段）**
  - 仅限 admin、store_manager、salesperson 角色访问
  - 通过 `/api/customers_detail`、`/api/customer_detail/<customer_id>` 端点获取
  - 所有访问会记录到审计日志
- `wechat`: String(128) - **客户微信号（敏感字段）**
  - 仅限 admin、store_manager、salesperson 角色访问
  - 通过 `/api/customers_detail`、`/api/customer_detail/<customer_id>` 端点获取
  - 所有访问会记录到审计日志

**权限控制：**
- 普通API（如`/api/customer_list`）不返回phone和wechat字段
- 需要通过特殊权限端点访问敏感信息
- 所有敏感字段访问会记录到`log/audit_sensitive_access.log`审计日志

**关系：**
- 一对多：一个客户可以有多个收货人（ReceiverTable）

### ReceiverTable
收货人表，存储客户的收货地址信息：
- `id`: 收货人记录ID
- `customer_id`: 关联的客户ID（外键）
- `receiver`: 收货人姓名
- `receiver_phone`: 收货人电话
- `mail`: 邮箱
- `country`: 国家
- `province`: 省份
- `city`: 城市
- `address`: 详细地址
- `zip_code`: 邮编

## 功能特性
- 客户信息的增删改查
- 一个客户可以有多个收货地址
- 收货人信息与客户关联（一对多关系）
- 支持完整的地址信息管理
- **敏感数据保护**：客户phone和wechat字段受权限控制
  - 只有admin、store_manager、salesperson可以访问
  - 所有访问会记录审计日志
  - 通过专用API端点管理（`/api/customers_detail`、`/api/customer_detail/<customer_id>`、`/api/customer_info/<customer_name>`）

## API端点

### 普通端点（所有登录用户可访问）
- `GET /api/customer_list` - 获取客户名称列表（不含敏感字段）
- `GET /api/receiver_list/<customer_name>` - 获取收货人列表
- `GET /api/receiver_info_list/<customer_name>` - 获取收货人详情
- `GET /api/receiver_info/<receiver_id>` - 获取单个收货人信息
- `POST /api/del/<customer_name>/<receiver_id>` - 删除收货人
- `POST /api/del_customer/<customer_name>` - 删除客户（级联删除）
- `GET /api/excel` - 下载Excel模板（无需认证）

### 敏感数据端点（需要特殊权限）
**权限要求**：admin、store_manager、salesperson

- `GET /api/customers_detail` - 获取所有客户详情（含phone、wechat）
- `GET /api/customer_detail/<customer_id>` - 获取单个客户详情（含phone、wechat），使用主键ID查询
- `POST /api/customer_info/<customer_name>` - 更新客户联系信息（phone、wechat）

**审计日志**：
所有敏感数据访问会自动记录到`log/audit_sensitive_access.log`，包含：
- 用户ID、角色、姓名
- 操作类型（查看全部/查看单个/更新）
- 客户名称（如适用）
- 客户端IP地址
- 时间戳

## 使用场景
- 订单创建时选择客户和收货地址
- 客户资料管理
- 物流信息填写
- 发货单生成
