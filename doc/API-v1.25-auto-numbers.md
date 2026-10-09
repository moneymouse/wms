# API v1.25：按需生成订单号和原单号

订单详情页新增「生成订单号」与每个包裹/货箱的「生成原单号」按钮。仅点击对应按钮时生成并立即保存对应号码；打开页面、新建订单、添加或分配货箱均不会自动生成。原有手动输入和保存接口保持不变，手动号码不做新增查重限制。

## 格式与防碰撞

v1.32 起自动订单号和原单号统一为 **`D` 前缀、9 位数字、`L` 后缀，数字首位为 8**，例如 `D800012345L`，共 11 个字符。详见 [API v1.32](API-v1.32-shipping-layout-and-number-format.md)。生成的是系统内部号码，不代表 DHL 签发的运单；已保存和手动号码保持原样。

使用安全随机数生成候选值，分别查询 `orders.order_id` 与 `cargos.transfer_id`，两类号码共用查重范围，包含归档数据。遇到重复时重新生成，最多尝试 100 次。现有迁移已提供非唯一索引 `idx_orders_order_id`、`idx_cargos_transfer_id`；不新增表、不修改唯一约束、不需要数据库迁移。

MySQL/MariaDB 使用专用连接上的 `GET_LOCK` 将自动生成请求串行化，查重、字段写入和订单版本记录在同一事务中完成，提交或回滚后释放锁再归还连接；SQLite 使用 `BEGIN IMMEDIATE`。手动写入沿用原规则，不受该生成锁或查重限制。被删除或后来被手动覆盖的号码不作永久保留。

## 接口

两个接口都要求 `x-token`，允许 `admin`、`store_manager`、`salesperson`、`clerk`（含多角色账号）。

### 生成订单号

`POST /api/orders/<order_uid>/generate-order-number`

可省略请求体或传 `{}`；推荐传页面当前已保存值用于并发检查：

```json
{"expected_value": "旧订单号"}
```

成功示例：

```json
{"code":200,"msg":"订单号已生成","data":{"uid":"ORDER_UID","order_uid":"ORDER_UID","order_id":"D800012345L","current_version":3}}
```

只修改该订单的 `order_id` 与 `update_date`，不改变包裹原单号。

### 生成包裹或货箱原单号

`POST /api/orders/<order_uid>/cargo/<cargo_uid>/generate-original-number`

请求体规则相同，`expected_value` 为该货物当前已保存的 `transfer_id`。

```json
{"code":200,"msg":"原单号已生成","data":{"uid":"CARGO_UID","order_uid":"ORDER_UID","transfer_id":"D800012346L","current_version":4}}
```

锁定当前订单和货物后核对订单归属，只修改目标货物的 `transfer_id` 与 `update_date`。不修改转单号、重量、其它货物或订单号，不触发出库或追踪注册。当前已出库货箱不可修改原单号；v1.26 起撤销出库后恢复原单号编辑与生成，出库/成本历史仍保留。归档订单、货物或装箱单不可生成。

## 错误与历史

| HTTP / code | 含义 |
| --- | --- |
| 400 | 请求不是 JSON 对象、包含未知字段，或 `expected_value` 不是字符串/null |
| 401 / 403 | 未认证或角色无权限 |
| 404 | 订单或货物不存在/已归档 |
| 409 | 页面保存值已过期、货物已不属于当前订单、装箱单已归档，或货箱当前已出库 |
| 503 | 生成锁等待超时或连续候选号码均已使用 |

`expected_value` 允许字符串或 null；null 与空字符串都表示未填号码。不传时不执行页面旧值检查。前端传已保存值，不使用尚未保存的输入草稿，失败时展示服务端原因并保留其它草稿。

号码写入和订单历史一起提交，历史 action 分别为 `order_number_generated`、`original_number_generated`，包含操作人及变更前后值；任一步失败则回滚号码和该次版本记录。
