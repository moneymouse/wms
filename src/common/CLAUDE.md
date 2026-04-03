# Common Module

通用工具函数和静态数据配置，为整个应用提供基础功能支持。

## Data Configuration

| 文件                | 说明                                  |
| ------------------- | ------------------------------------- |
| `countryList.js`    | 200+ 国家/地区选项列表 (中英文双语)   |
| `transportation.js` | 运输方式选项 (TC/DPD/DHL等17种渠道)   |
| `orderProperty.js`  | 订单字段属性定义 (字段名、标签、宽度) |
| `trackStatus.js`    | 17Track 物流状态映射 (30+ 状态码)     |
| `roleConfig.js`     | 角色权限配置 (菜单/路由权限控制)      |

## Utilities

| 文件                 | 说明                                              |
| -------------------- | ------------------------------------------------- |
| `safeHeader.js`      | API安全头部，添加时间戳(x-time)和JWT令牌(x-token) |
| `generateOrderID.js` | 订单ID生成器，基于IP+时间戳生成唯一标识           |
| `genWayBill.js`      | 运单Excel下载，调用后端API生成文件                |

## Components

| 文件             | 说明                                                 |
| ---------------- | ---------------------------------------------------- |
| `uploadOrder.js` | 订单批量上传组件 (Ant Design Dragger)，支持Excel导入 |

## Dependencies

- `antd` - UI组件库
- `xlsx` - Excel文件处理
