# API v1.32：出货单排版与自动单号格式

## 出货单 PDF

订单、装箱单及出货确认单草稿的 PDF 共用 A4 纵向、一行一单的整页宽度版式。正文与箱子明细为 12 号字，标题 18 号、列标题 11 号、订单或装箱单标识 10 号；蓝色抬头、灰色表头与内嵌中文字体保留。

单据之间保留 6 mm 间隔，使用横向虚线裁切线。普通订单或分组保持完整，不因下一张单据而拆分；超过整页可打印高度时才生成续单，每份续单重复客户、代理、备注、订单或装箱单标识及明细列标题。长唛头和原单号继续自动换行，所有箱子按原顺序完整输出。

同一单据内相邻唛头组之间，在前一组末行下方绘制横跨两列的 1.2 pt 蓝色粗线。装箱单与草稿打印按装箱单编号识别分组；订单打印将标准唛头末尾的 `_箱号` 去除后识别分组，不改变箱子顺序或增加空行。

以下接口的请求、选择范围、角色和版本校验、响应头及错误契约不变：

- `POST /api/orders/shipping-confirmation/pdf`
- `POST /api/packing-lists/shipping-confirmation/pdf`
- `POST /api/shipping-confirmation-drafts/<uid>/pdf`

打印仍为只读导出，不改变订单、箱子、出库或财务状态。

## 自动订单号与原单号

新生成的订单号和原单号统一为 `D8xxxxxxxxL`，其中 `x` 为数字，共 11 个字符，例如 `D800012345L`。前缀为 `D`、后缀为 `L`，中间保留原有 9 位数字（首位 `8`，后 8 位安全随机生成并补齐前导零）。现有已保存号码及手动输入不作转换。

以下接口共用此格式与订单号 / 原单号完整字符串的查重范围：

- `POST /api/orders/<order_uid>/generate-order-number`
- `POST /api/orders/<order_uid>/cargo/<cargo_uid>/generate-original-number`
- `POST /api/packing-lists/<packing_uid>/boxes/generate-original-numbers`

归档数据继续参与查重；最多尝试 100 次，耗尽后返回 503。MySQL/MariaDB 专用连接生成锁、SQLite `BEGIN IMMEDIATE`、权限、当前出库限制、`expected_value` / `expected_values` 并发保护、原子写入和订单版本历史保持不变。只在用户点击生成时分配号码；查看、创建和手动保存不会触发自动生成。无需数据库迁移。
