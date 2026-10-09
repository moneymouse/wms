# Controllers 控制器层

## 功能概述
控制器层负责处理HTTP请求和响应，是系统的入口层。接收客户端请求，调用服务层处理业务逻辑，并返回响应结果。

## 主要模块

### auth_controller.py
用户认证控制器，处理用户注册、登录、登出、权限验证等认证相关的HTTP请求。包含用户管理、审批等功能。

### order_controller.py
订单控制器，处理订单的创建、查询、更新、删除等HTTP请求。管理仓库订单的完整生命周期。

### cargo_controller.py
货物控制器，处理货物的增删改查、库存管理等HTTP请求。是仓库管理的核心功能模块。

### customer_controller.py
客户控制器，处理客户信息的管理，包括客户和收货人信息的CRUD操作。

### log_controller.py
日志控制器，提供操作日志的查询接口，用于审计和追溯系统操作。

## 技术特点
- 使用Flask Blueprint组织路由
- 统一的错误处理和响应格式
- JWT token认证和权限控制
- RESTful API设计风格
