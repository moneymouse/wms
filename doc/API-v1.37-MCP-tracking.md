# API v1.37 — MCP 订单包裹与物流查询

MCP 独立只读工具 `get_tracking` 接收业务订单号，返回该订单下包裹的基本信息、
仓储状态和物流摘要，对应网页 `GET /api/orders/<uid>/cargo` 的包裹详情用途。
工具自行解析内部 UID；`get_order` 保持原有行为，没有新增 REST 路由。

## 权限与参数

需要已审核的 WMS OAuth 账号，并同时授权 `mcp`、`tracking:read`。
账号角色规则与 `get_order` 相同，不另加订单列表的角色限制。
`tools/list` 返回五个工具；没有 `tracking:read` 仍可发现本工具的 Schema，
实际调用会检查 scope。

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `order_id` | string | 是 | 真实业务订单号；去除首尾空格后非空，最多 128 字符 |

仅接受 `order_id`。服务端按未归档 `OrderTable.order_id` 精确查找，不通过
`list_orders` 模糊搜索，也不把内部订单 UID、原单号或转单号当作订单号。
原 REST `GET /api/orders/<uid>/cargo` 中的路径参数是内部 UID，与本工具不同。

调用示例，`EXAMPLE-ORDER` 仅为占位值：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_tracking",
    "arguments": {"order_id": "EXAMPLE-ORDER"}
  }
}
```

## 查询行为

精确定位未归档订单后，读取订单下包裹并整理基本字段。将本次请求中有效的
转单号去重，每 40 个一批直接 POST 到现有 17TRACK API v2.2 `/getTrackInfo`，
复用服务端配置。同号包裹共用本次请求得到的查询结果，这是同次请求内去重，
不保存为缓存；下次调用重新请求 17TRACK。无转单号的包裹不请求物流。

本工具不自动注册追踪号，不修改订单或货物仓储状态。MCP 沿用工具调用审计，
不将物流轨迹写入货物记录。返回只包含下文定义的字段，不返回完整轨迹事件列表
或第三方运输商配置。

17TRACK 自己的承运商采集可能滞后，不能保证刚发生的事件已经收录，也不承诺
强制刷新承运商轨迹。`queried_at` 是本次查询时间，事件时间看包裹的
`tracking.latest_event.time`。

## 成功返回

业务结果位于 MCP `result.structuredContent`。订单存在时返回包裹列表，
即使部分包裹的物流查询失败，外层仍可为 `code=200`、`isError=false`；客户端
须同时检查 `tracking_complete` 和每个包裹的 `tracking.error`。

```json
{
  "code": 200,
  "data": [
    {
      "uid": "EXAMPLE-CARGO-UID",
      "box_number": 1,
      "item_name": "示例货物",
      "weight": 10.5,
      "transfer_id": "EXAMPLE-ORIGINAL-NUMBER",
      "waybill_id": "EXAMPLE-WAYBILL",
      "warehouse_status": 1,
      "warehouse_status_text": "已出库",
      "tracking": {
        "status": "Delivered",
        "sub_status": "Delivered_Other",
        "status_text": "成功签收",
        "description": "",
        "latest_event": {
          "time": "2026-10-07T08:00:00+08:00",
          "location": "示例地点",
          "description": "示例签收事件"
        },
        "error": null
      }
    }
  ],
  "total": 1,
  "order_id": "EXAMPLE-ORDER",
  "order_uid": "EXAMPLE-ORDER-UID",
  "queried_at": "2026-10-07T01:00:00Z",
  "tracking_complete": true
}
```

| 顶层字段 | 含义 |
| --- | --- |
| `data` | 本订单包裹数组，不分页 |
| `total` | 返回包裹数 |
| `order_id` | 本次精确匹配的业务订单号 |
| `order_uid` | 服务端解析出的内部订单 UID |
| `queried_at` | 本次查询的 UTC ISO 8601 时间，末尾 `Z` |
| `tracking_complete` | 有转单号的物流查询是否全部成功；无转单号包裹或空包裹列表不算失败 |

每个包裹只返回以下字段：

| 包裹字段 | 含义 |
| --- | --- |
| `uid` | 包裹内部 UID |
| `box_number`、`item_name`、`weight` | 箱号、货名、重量 |
| `transfer_id`、`waybill_id` | WMS 保存的原单号、转单号 |
| `warehouse_status` | WMS 数据库原仓储状态值 |
| `warehouse_status_text` | 按 WMS 仓储规则表示“待出库”或“已出库”，不被 17TRACK 状态覆盖 |
| `tracking` | 物流摘要；没有有效转单号时为 `null` |

`tracking` 非空时只包含六个字段：

| 物流字段 | 含义 |
| --- | --- |
| `status` | 17TRACK 主状态，如 `Delivered`、`InTransit`、`NotFound` |
| `sub_status` | 17TRACK 子状态，如 `Delivered_Other` |
| `status_text` | 中文状态，如“成功签收”“派送途中”；未知状态显示“未知物流状态”，原始代码仍保留 |
| `description` | 上游状态说明，可为空 |
| `latest_event` | `null` 或 `{time,location,description}`，仅保留最新一条事件的这三个字段 |
| `error` | 成功时为 `null`；失败时为 `{code,msg}` |

最新事件 `time` 优先取上游 UTC 时间，其次 ISO 时间，再取原始日期与时间组合；
保留上游时区字符串，不猜测时区，没有时间则为 `null`。

成功查询不等于成功签收。17TRACK 接受查询但状态为 `NotFound`，或已注册但
暂无轨迹时，中文状态为“暂无物流轨迹”，`tracking.error=null`，不使
`tracking_complete` 变为 false。仓储状态与运输状态分别解释。

## 错误与部分失败

订单识别失败时外层返回 `{code,msg}`、`isError=true`：

| 外层 code | 场景 / msg |
| --- | --- |
| `400` | 参数 Schema 校验失败：`Invalid arguments: ...` |
| `404` | `订单不存在`，包括已归档订单 |
| `409` | `订单号对应多个未归档订单，请先处理重复订单号` |

OAuth 认证和权限错误沿用现有 HTTP 401/403。HTTP 成功不代表业务成功，
外层 `code=200` 也不代表所有包裹物流成功。

物流上游问题仅标记受影响包裹的 `tracking.error`，外层继续返回订单包裹列表，
并设 `tracking_complete=false`。错误不包含原始异常或上游请求细节：

| 包裹 error.code | error.msg / 场景 |
| --- | --- |
| `400` | `转单号或承运商参数无效`；或 `此转单号匹配多个承运商，无法确定物流状态` |
| `404` | `未查询到此转单号的物流信息`；或 `此转单号尚未注册物流追踪` |
| `429` | `物流服务请求过于频繁，请稍后重试` |
| `502` | `物流服务暂时不可用，请稍后重试`；或 `物流服务返回无效响应` |
| `504` | `物流查询超时，请稍后重试` |

例如某包裹未注册时，其 `tracking.error` 为：

```json
{"code":404,"msg":"此转单号尚未注册物流追踪"}
```

该包裹基本信息仍返回。客户端应展示具体失败原因，不能把物流查询失败显示为
“待出库”或“已签收”。超时、限流或服务异常可稍后重查订单；不能因此自动注册
转单号或写入仓储状态。

## 工具发现与授权

scope 继续使用 `mcp tracking:read`，授权页显示“查询订单下包裹及物流状态”。
已有 `tracking:read` 的令牌无需因参数改为订单号而追加 scope；重新发现工具，
获取当前 `order_id` 输入和包裹列表输出 Schema 即可。

尚未授予 `tracking:read` 的旧授权仍须重新同意此权限；令牌刷新不会扩大
scope。如果旧客户端登记范围不含此权限，需要重新注册后授权。
Skill Python 客户端的默认读取权限和 `--all-scopes` 已包含此权限：

```sh
python3 scripts/wms_mcp.py tools-list
python3 scripts/wms_mcp.py call get_tracking --arguments '{"order_id":"EXAMPLE-ORDER"}'
```

仅查询订单包裹和物流可授权 `mcp tracking:read`，无需订单列表 scope：

```sh
python3 scripts/wms_mcp.py login --scope 'mcp tracking:read'
```

Codex 原生客户端需要重新授权时使用：

```sh
codex mcp login wms-pre --scopes mcp,orders:list,orders:read,tracking:read
```

具体接入及 DCR 兼容方式见
[WorkBuddy / Codex 接入说明](../integrations/workbuddy/wms-mcp/references/workbuddy-setup.md)。
重新授权前先核实状态不确定的创建请求，避免更换 OAuth 客户端后重复创建。

本次不增加数据库结构或迁移，也不改变现有 REST 订单包裹详情行为。
