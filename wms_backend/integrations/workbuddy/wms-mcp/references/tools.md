# 工具与业务参数

优先读取服务端 `tools/list` 提供的实时输入、输出 Schema，以下说明帮助解释业务字段。
所有工具还需要基础 `mcp` scope。输入不接受任意未知字段。

## 查询

### list_orders

需要 `orders:list`，账号角色为管理员、店长、业务员或文员之一。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `p` | 1 | 页码，最小 1 |
| `s` | 30 | 每页条数，范围 1–200 |
| `q` | 空字符串 | 沿用现有网页的搜索规则 |
| `sf` | `create_date` | 排序字段 |
| `so` | 1 | 1 降序、0 升序 |

调用示例：

```json
{"p":1,"s":3,"sf":"create_date","so":1,"q":""}
```

列表返回 `data` 和 `total`。本页条数不等于总条数；跨页查询按用户要求进行。

### get_order

需要 `orders:read`，输入为 `{"uid":"实际订单UID"}`。
业务订单号 `order_id` 与内部 `uid` 不同；用户只给订单号时先搜索列表取得 UID。
详情包含原接口的编辑策略和版本信息。无此订单或已归档返回 `code=404`。

### get_tracking

需要 `tracking:read`，只输入真实业务订单号：

```json
{"order_id":"用户提供的真实业务订单号"}
```

`order_id` 去除首尾空格后须非空，最多 128 字符。服务端精确查找未归档订单并
自行解析内部 UID，不通过 `list_orders` 模糊搜索。它与原 REST 包裹详情的 UID
参数不同。订单不存在或已归档返回 404，重复业务订单号返回 409。

成功返回 `{code:200,data:[包裹],total,order_id,order_uid,queried_at,tracking_complete}`。
`data` 每包只含 `uid`、`box_number`、`item_name`、`weight`、`transfer_id`、
`waybill_id`、`warehouse_status`、`warehouse_status_text` 和 `tracking`。
`tracking` 只含 `status`、`sub_status`、中文 `status_text`、`description`、
`latest_event` 和 `error`；`latest_event` 为 `null` 或 `{time,location,description}`。
例如 `sub_status=Delivered_Other`、`status_text=成功签收`。
仓储状态和物流状态分别解释，不能互相覆盖。

无转单号的包裹 `tracking=null`。查询失败只在对应包裹的 `tracking.error`
给出 `{code,msg}`；外层仍为 200，`tracking_complete=false`。
`tracking_complete` 表示有转单号的查询是否全部成功，无转单号包裹或空包裹列表
不算失败。`NotFound` 表示“暂无物流轨迹”，属于成功查询，不代表已签收。

每次调用将本订单转单号在同次请求内去重，每 40 个一批直接查 17TRACK，
不使用 WMS 物流缓存、不自动注册、不修改订单或货物。返回信息仍取决于
17TRACK 的采集进度；`queried_at` 是本次查询时间，不是物流事件发生时间。

## 创建

### create_order

需要 `orders:create`。顶层参数只有 `order` 和 `idempotency_key`。
订单业务字段放在 `order` 内，不能平铺在工具参数顶层。

可用字段：`customer_id`、`customer_name`、`order_id`、`transportation`、
`receiver`、`receiver_phone`、`mail`、`country`、`province`、`city`、
`address`、`en_name`、`cn_name`、`total_weight`、`post_code`、`zip_code`、
`order_date`、`tag_all`、`salesman_id`、`quote`。只传用户任务实际提供或查询
得到的字段，省略未提供的可选字段。以实时 Schema 和业务错误确定必需条件。

`quote` 支持每公斤单价 `unit_price`，兼容 `quoted_price`，二者至少其一；
可选 `surcharge` 默认 0、`quote_remark`。金额和重量不能为负。
客户、收件人、订单版本、初始报价、审计和幂等结果在同一事务中提交。

形状示例，示例值不能自动用于实际创建：

```json
{
  "idempotency_key":"为本次逻辑创建生成的UUID",
  "order":{
    "order_id":"用户指定的订单号",
    "receiver":"用户指定的收件人",
    "country":"用户指定的国家",
    "total_weight":12.5,
    "quote":{"unit_price":20,"surcharge":0}
  }
}
```

### create_packing_list

需要 `packing_lists:create`。账号角色为管理员、店长、业务员、工人或员工之一。

参数：必填 `idempotency_key`，唛头使用 `mark` 或 `list_number`，
可选 `customer_id` 和 `photos`（已有图片 URL 数组，默认空数组）。
两个唛头字段都存在时 `list_number` 优先；服务端去除首尾空格并转大写。

只创建状态为 `draft` 的装箱单表头，不添加箱子或绑定订单；创建者来自 OAuth。
不要传入 `status`、`creator_id`、角色或审计字段。

```json
{"idempotency_key":"为本次逻辑创建生成的UUID","mark":"用户指定的唛头","photos":[]}
```

## 返回与错误

工具结果包含 `structuredContent` 和简短文本。业务成功 `code=200`；
创建订单返回 `uid`，装箱单的 UID 位于返回的 `data` 中，以实际结果为准。
`isError=true` 或业务 `code` 非 200 时解释服务端 `msg`。
同键同参数返回原结果；同键不同参数返回 409，不能改键来掩盖状态不确定的重复创建。
