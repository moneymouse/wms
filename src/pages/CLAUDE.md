# Pages Module

应用页面组件，实现核心业务功能。

## Authentication

| 文件       | 说明                                            |
| ---------- | ----------------------------------------------- |
| `login.js` | 登录/注册页面，JWT认证，token存储于localStorage |
| `admin.js` | 用户管理页面 (仅管理员)，审批新用户、角色管理   |

## Order Management

| 文件             | 说明                                       |
| ---------------- | ------------------------------------------ |
| `newOrder.js`    | 创建订单页面，表单自动保存，通讯录快速选择 |
| `orderList.js`   | 订单列表页面，分页查询、批量导出、搜索过滤 |
| `orderDetail.js` | 订单详情页面，包裹管理、17Track物流时间线  |

## System

| 文件      | 说明                                      |
| --------- | ----------------------------------------- |
| `logs.js` | 操作日志页面 (仅管理员)，显示系统操作记录 |

## Warehouse Operations

| 文件          | 说明                                       |
| ------------- | ------------------------------------------ |
| `normal.js`   | 收货/出货操作页面，录入原单号、件数、重量  |
| `scanner.jsx` | 条码扫描器页面，使用zxing库识别条码/二维码 |

## Styles

| 文件                     | 说明                           |
| ------------------------ | ------------------------------ |
| `newOrder.module.css`    | 新建订单页面样式 (CSS Modules) |
| `orderDetail.module.css` | 订单详情页面样式 (CSS Modules) |

## Route Configuration

路由定义见 `src/router.js`
