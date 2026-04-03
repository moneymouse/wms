# WMS Frontend

基于 React 18 + Ant Design 的仓库管理系统前端，支持订单管理、物流跟踪、运单导出及用户权限控制。

## Directory Structure

| 目录                                  | 说明                                    |
| ------------------------------------- | --------------------------------------- |
| [common/](./common/CLAUDE.md)         | 通用工具函数、数据配置和API安全认证模块 |
| [components/](./components/CLAUDE.md) | 可复用UI组件：导出按钮、自动完成输入框  |
| [pages/](./pages/CLAUDE.md)           | 页面组件：订单管理、用户认证、系统日志  |

## Key Files

| 文件        | 说明                                    |
| ----------- | --------------------------------------- |
| `App.js`    | 应用主布局，侧边栏导航，JWT角色权限控制 |
| `router.js` | React Router 路由配置                   |
| `config.js` | API端点配置                             |
