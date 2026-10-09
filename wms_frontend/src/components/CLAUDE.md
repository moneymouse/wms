# Components Module

可复用UI组件，封装常用业务交互逻辑。

## ExportButton.js

订单导出下拉按钮，支持多种物流商格式：

**支持格式**: 极飞、统仓、统仓UPS、金飞旗、环世通、星航、金龙、金龙快递、亚轩、亚轩WE、面单、转单号列表

**Props**:
- `selectedKeys` - 选中订单UID列表
- `selectedCargos` - 选中包裹列表
- `data` - 订单数据源
- `onSuccess` - 导出成功回调

## GoodName.js

商品名称自动完成输入框。

**预设品名**: CLOTH, T-SHIRT, SWEATSHIRT, VEST, DRESS, SUIT, BAG, WALLET, BACKPACK 等 25+ 项

**Props**: `onChange`, `onBlur`, `onEnter`, `defaultValue`, `ref`

## transportation.js

运输方式自动完成输入框，数据源来自 `common/transportation.js`。

**Props**: `onChange`, `onBlur`, `onEnter`, `defaultValue`

## Usage Pattern

所有组件基于 Ant Design AutoComplete 封装，支持模糊搜索过滤。
