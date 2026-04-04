# Data 数据层

## 功能概述
数据层负责数据持久化、数据库操作和数据迁移。使用SQLAlchemy ORM管理数据模型，提供统一的数据访问接口。

## 主要模块

### database.py
数据库配置和会话管理，定义SQLAlchemy Base和SessionFactory。

### DB.py
主数据库操作模块，提供货物和订单的CRUD操作接口。包含复杂的数据查询和统计功能。

### DB_sqlite.py
SQLite数据库的旧版实现，用于数据迁移参考。

### backup.py
数据备份模块，实现数据库的自动备份功能，保证数据安全。

### migrate.py
数据迁移模块，处理从旧数据格式到新数据库结构的迁移。

### excels.py
Excel数据处理模块，负责导入导出Excel格式的数据。

## 子模块

### customer/
客户数据模型和操作，详见 [customer/AGENTS.md](customer/AGENTS.md)

### user/
用户数据模型和操作，详见 [user/AGENTS.md](user/AGENTS.md)

### data/
数据文件存储目录，存放序列化的数据文件。

### history/
历史数据归档目录，存放历史记录和备份。

## 数据存储
- **主数据库**: SQLite (位置由配置决定)
- **数据文件**: 序列化的pickle文件（旧版兼容）
- **备份记录**: backupRecord.txt
