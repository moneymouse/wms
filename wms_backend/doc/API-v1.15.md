# API v1.15：地址国家纠错与邮编核实

日期：2026-10-03。创建订单的“解析地址”改为 DeepSeek Function Calling 提取字段，后端使用 API Ninjas Postal Code API 核实城市、省/州，再返回表单草稿。

## 请求与公开响应

继续使用 `POST /api/orders/parse-address`，JWT 请求头 `x-token`，JSON 请求体 `{"address":"完整收货地址"}`。沿用非空字符串、最多 4000 字符及请求体最多 32 KiB 的限制。

成功响应仍为 HTTP 200：

```json
{
  "code": 200,
  "data": {
    "country": "ES",
    "province": "Madrid",
    "city": "Madrid",
    "zip_code": "28001",
    "receiver": "Jane Doe",
    "receiver_phone": "",
    "mail": "",
    "warnings": []
  }
}
```

示例值只说明字段格式，实际城市和省/州取查询结果。七个表单字段都是字符串，缺失值为空字符串。`country` 为 ISO 3166-1 alpha-2 大写代码，前端映射为现有国家选项，例如 `ES` → `SPAIN`。不返回 `address`、`country_name`、`country_source` 或上游工具调用数据。

详细地址保留用户原文，包括其中的国家错字。邮编及联系方式仍从原文提取，保留邮编前导零；姓名、电话、邮箱不猜测。空字段不清除前端已填值。继续避免解析期间用户修改的字段被较早请求覆盖。接口不写订单、客户或收货人，响应保持 `Cache-Control: private, no-store`。

## DeepSeek 工具调用与国家校验

使用 `POST /chat/completions`，`tools` 定义 `resolve_order_address`，通过命名 `tool_choice` 强制调用；关闭思考，非流式，温度 0，最多 4096 输出 token。不再使用 JSON Output 的 `response_format`。

工具参数包括七个表单字段、`warnings`，以及内部字符串 `country_name`（修正后标准国家名称）、`country_source`（逐字抄录的原文国家文本）。所有参数均需提交；未知字符串为空字符串。仅接受完成原因 `tool_calls`、恰好一次正确函数调用及合法参数 JSON/类型。工具参数校验后，由后端执行邮编查询并直接合并结果，无需第二次模型生成。

模型 `warnings` 通常为空，只允许一条固定提示：`存在多个地址` 或 `地址信息有歧义`。正常纠错、缺少姓名/电话/邮箱等可选信息不产生提示；后端过滤模型输出的其他说明、纠错通知及免责声明。

国家代码、名称及原文证据必须互相一致。使用 `pycountry` 的 ISO 国家名称、官方名、常用名，并保留现有中文及物流别名。完整英文国家名支持唯一的一处字母插入、删除、替换或相邻字母交换，例如 `SPIAN` → `SPAIN` → `ES`。两字码及三字母缩写不做模糊纠正；多处错字或多个国家都可能匹配时留空并提示。原文没有明确国家时不根据城市、邮编或电话猜国家。省州代码如 `Los Angeles, CA 90001` 中的 `CA` 不作为加拿大证据；明确 `country: CA` 或独立国家末行可以消除歧义。

## 邮编查询与合并

国家及邮编有效时，后端请求 `GET https://api.api-ninjas.com/v1/postalcode`，查询参数为 `country` 和 `postal_code`，请求头为 `X-Api-Key`，固定 10 秒超时，响应最大 128 KiB，无自动重试。所有国家本次仅使用此接口，美国不接另一 Zip Code API。

校验响应数组、国家一致及非空且不超长的城市、省州字段；接口 `city` → 表单 `city`，`region` → 表单 `province`，保留原文 `zip_code`。接口字段是独立数据来源，不要求已出现在原地址中。重复城市/省州候选合并，比较时忽略大小写、空白和标点。

- 唯一候选优先修正城市、省州；正常修正或补全不添加警告。
- 多个候选先按原城市匹配，原省州名称或接口可选的 `region_code` 可进一步区分；唯一城市匹配不因原省州写错而被拒绝。
- 无法唯一匹配时保留原城市；全部候选共有的非空省州仍可回填，否则保留原省州，并提示人工核对。
- 缺国家/邮编、缺查询密钥、查询超时/失败/限流、无匹配结果、国家无邮编或异常响应，均保留已通过原文校验的提取字段并添加安全警告。邮编查询失败不会使整个解析失败。

最终 `warnings` 最多 3 条，每条最多 60 字符，仅保留影响填写的具体问题。校验不通过的字段合并为一条 `请确认：收件人、邮箱` 等提示；省州/城市由邮编查询继续核实，不提前重复提醒。邮编警告使用 `邮编查询失败`、`邮编无匹配结果`、`邮编对应多个城市` 等短句，不再重复“保留原结果”“请人工核对”。空解析结果已有原因时不追加缺国家/邮编提醒。错误及警告不包含密钥、上游错误正文或原始详细地址；不记录请求体。

DeepSeek 的配置、认证、限流、响应截断等失败继续沿用 [v1.13 的错误状态码](API-v1.13.md#错误响应)。地址提取失败不执行邮编查询。

## 配置与验证

后端 `env.toml` 顶层新增 `api_ninjas_api_key`，每次请求读取，忽略环境变量及 `.env`。配置示例：

```toml
deepseek_api_key = "实际 DeepSeek 密钥"
deepseek_base_url = "https://api.deepseek.com"
deepseek_model = "deepseek-flash"
deepseek_timeout_seconds = 90
api_ninjas_api_key = "实际 API Ninjas 密钥"
```

新增运行时依赖 `pycountry==26.2.16`，通过后端依赖清单安装。邮编密钥为空时只禁用查询，仍返回提取结果及提醒；DeepSeek 密钥为空时维持原来的 503。真实配置继续仅存在后端，Docker Compose 运行时只读挂载，不提交密钥。

单元及接口测试模拟两个供应商，不发送真实地址或消耗接口额度。覆盖国家纠错、歧义拒绝、工具调用结构、唯一与多个邮编候选、配置重读、查询失败回退，以及前端国家映射和保留原地址/用户编辑。

协议参考：[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[API Ninjas Postal Code](https://api-ninjas.com/api/postalcode)、[pycountry](https://github.com/pycountry/pycountry)。
