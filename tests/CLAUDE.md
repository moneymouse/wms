# Tests 测试模块

## 功能概述
测试模块提供完整的自动化测试套件，包括单元测试、集成测试和测试工具。确保代码质量和系统稳定性。

## 目录结构

### unit/
单元测试目录，测试独立的函数和类：
- `test_auth_controller.py` - 认证控制器测试
- `test_auth_service.py` - 认证服务测试
- `test_order_controller.py` - 订单控制器测试
- `test_order_service.py` - 订单服务测试
- `test_cargo_controller_part1.py` - 货物控制器测试（第一部分）
- `test_cargo_controller_part2.py` - 货物控制器测试（第二部分）
- `test_cargo_service.py` - 货物服务测试
- `test_customer_controller.py` - 客户控制器测试
- `test_log_controller.py` - 日志控制器测试

### integration/
集成测试目录，测试模块间的协作：
- `test_end_to_end_workflows.py` - 端到端工作流测试

### fixtures/
测试夹具目录，存放测试数据和配置文件。

## 测试工具

### conftest.py
pytest配置文件，定义测试夹具和全局配置：
- 数据库测试会话
- Mock对象配置
- 测试应用实例
- 测试环境初始化

### factories.py
测试数据工厂，使用Factory Boy生成测试数据：
- UserFactory - 用户测试数据
- CustomerFactory - 客户测试数据
- OrderFactory - 订单测试数据
- CargoFactory - 货物测试数据

### base.py
测试基类，提供通用的测试方法和工具。

### test_config.py
测试配置管理。

### test_mock_verification.py
Mock验证测试，确保Mock对象正确使用。

## 测试运行
- `run_tests.py` - 测试运行脚本
- `setup_test_env.py` - 测试环境配置
- `test_fixes.py` - 测试修复工具

## 测试策略
- **单元测试**: 覆盖独立模块功能
- **集成测试**: 验证模块间协作
- **Mock隔离**: 使用Mock隔离外部依赖
- **工厂模式**: 使用Factory生成测试数据
- **夹具复用**: 通过pytest fixture提高测试效率
