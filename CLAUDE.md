# WMS 仓库管理系统后端

## 项目概述
基于Flask + SQLAlchemy构建的仓库管理系统（Warehouse Management System）后端服务。提供用户认证、订单管理、货物管理、客户管理等核心功能，支持RESTful API接口，采用三层架构设计（控制器-服务-数据）。

## 目录结构

### 核心业务模块
- [**controllers/**](controllers/CLAUDE.md) - 控制器层，处理HTTP请求和响应，系统入口
- [**services/**](services/CLAUDE.md) - 服务层，核心业务逻辑实现，事务管理
- [**data/**](data/CLAUDE.md) - 数据层，数据持久化、数据库操作和数据迁移
  - [**customer/**](data/customer/CLAUDE.md) - 客户和收货人数据模型
  - [**user/**](data/user/CLAUDE.md) - 用户认证和权限数据模型

### 支持模块
- [**utils/**](utils/CLAUDE.md) - 工具模块，日志管理和物流追踪等通用工具
- [**tests/**](tests/CLAUDE.md) - 测试模块，单元测试、集成测试和测试工具
- [**frontend/**](frontend/CLAUDE.md) - 前端静态资源，HTML、CSS、JavaScript

### 其他目录
- **excels/** - Excel文件存储目录
- **log/** - 日志文件存储目录
- **doc/** - 项目文档目录
- **migrations/** - 手工SQL迁移参考脚本（不作为自动迁移执行入口）
- **static/** - 静态文件资源
- **templates/** - 模板文件

## 技术栈
- **Web框架**: Flask
- **ORM**: SQLAlchemy
- **数据库**: SQLite
- **认证**: JWT Token
- **测试**: pytest + Factory Boy
- **Python**: 3.x

## 快速开始
1. 激活conda环境：`conda activate WMS`
2. 运行应用：`python app.py` 或 `flask run`
3. 运行测试：`python run_tests.py`

## 数据库迁移
本项目采用 **Alembic** 管理数据库版本，自动迁移入口为 `alembic/` 目录（由 `alembic.ini` 的 `script_location = alembic` 指定）。

当数据库结构发生更新后，请在项目根目录执行：

`docker-compose -f docker-compose.dev.yml run --rm backend alembic revision --autogenerate -m "your commit message"`

生成版本后建议执行：

`docker-compose -f docker-compose.dev.yml run --rm backend alembic upgrade head`

说明：`migrations/` 目录下的 `*.sql` 文件用于人工执行或对照参考，当前项目启动流程不会自动执行该目录下SQL。

## 接口变更
由于需要跟前端对接，每次接口更新后，将更新写入到[doc/API-v*.*.md](doc/)中。

## Environment
在执行Python任务之前，你需要通过在zsh里面执行`condactivate`从而激活conda环境，并且通过`conda activate WMS`切换到`WMS`的conda环境，里面有相关的依赖。

## Tips
你每次执行任务之前都说一句: "Hi, Master."会让我心情更好哦！

## For local information
load @CLAUDE.local.md