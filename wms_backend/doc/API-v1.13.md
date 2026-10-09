# API v1.13：订单地址解析

日期：2026-10-02。创建订单页面的详细地址输入框下新增“解析地址”链接，后端调用 DeepSeek 提取国家、省/州、城市、邮编和收件人联系方式，保留用户原输入的详细地址，用户核对后按原有流程创建订单。

后续国家纠错、Function Calling 与邮编核实流程见 [API v1.15](API-v1.15.md)；请求及公开响应结构保持兼容。

## 请求

`POST /api/orders/parse-address`

沿用订单创建的 JWT 认证（请求头 `x-token`）。`Content-Type: application/json`，请求体必须为对象：

```json
{"address":"Jane Doe\n123 Main St Apt 4\nLos Angeles, CA 90001\nUSA\n+1 (555) 123-4567\njane@example.com"}
```

`address` 必须为非空字符串，最多 4000 个字符；请求体最多 32 KiB。一次只传一个完整收货地址。

## 成功响应

HTTP 200：

```json
{
  "code": 200,
  "data": {
    "country": "US",
    "province": "CA",
    "city": "Los Angeles",
    "zip_code": "90001",
    "receiver": "Jane Doe",
    "receiver_phone": "+1 (555) 123-4567",
    "mail": "jane@example.com",
    "warnings": []
  }
}
```

七个字段均为字符串；未提供、存在歧义或无法核实的内容为空字符串。`country` 为 ISO 3166-1 alpha-2 大写代码，前端使用现有国家列表的 `label` 映射到表单 `value`（如 `US` → `USA`、`NL` → `NETHERLANDS, NL`）。其他字段保持原文拼写、缩写及邮编前导零。成功响应不包含 `address`，即使供应商返回该字段也会忽略。姓名、电话、邮箱不猜测，并核对是否出现在原文中。国家不能仅由城市或邮编推测；服务核实原文中的国家名称/代码，省/州或城市字段中的相同词需通过明确国家标签或独立国家行消除歧义。供应商返回的内部 `country_source` 证据不返回前端。`warnings` 为字符串数组，供前端提示人工核对。

接口仅返回草稿，不写入订单、客户或收货人记录。前端只将上述已识别字段填入当前创建表单，始终保留详细地址原输入，并忽略响应中的任何 `address` 字段；空字符串应保留用户原先的填写值。解析中若用户修改地址或受影响字段，应避免用较早请求的结果覆盖新输入。

## 错误响应

错误 JSON 为 `{"code":状态码,"msg":"可展示的安全提示"}`；认证错误沿用现有 JWT 响应。状态码如下：

- 400：请求非 JSON 对象、地址缺失、类型错误或超过 4000 字符。
- 401：系统 JWT 缺失或无效。
- 413：请求体超过 32 KiB。
- 502：上游服务失败、密钥被上游拒绝、响应格式异常、输出截断或响应超过 128 KiB。
- 503：后端未配置/配置错误、DeepSeek 余额不足或限流。
- 504：连接或读取超时。
- 500：未预期的内部错误，返回通用提示。

上游认证失败使用 502，避免前端误判为系统登录失效。接口响应设置 `Cache-Control: private, no-store`，错误提示不包含凭据、上游原始响应或原始收货地址；接口不套用记录请求体的操作日志装饰器。

## 配置与供应商协议

复用现有纸单识别设置及配置读取函数，不增加依赖。DeepSeek 只读取后端 `env.toml`，不再读取环境变量或后端 `.env`。新部署先在后端目录执行 `cp env.toml.example env.toml`，在文件顶层配置：

```toml
deepseek_api_key = "实际密钥"
deepseek_base_url = "https://api.deepseek.com"
deepseek_model = "deepseek-flash"
deepseek_timeout_seconds = 90
```

配置在每次调用时重新读取。文件或字段缺失时使用默认值：空密钥、`https://api.deepseek.com`、`deepseek-flash`、90 秒；空密钥禁用地址解析和纸单识别。Docker Compose 在运行时只读挂载该文件，真实配置不提交到 Git，也不打包进镜像。

密钥只保留在后端。服务地址必须为 HTTPS 且不含 URL 凭据、查询或片段；超时为 5–180 秒。模型通过 `deepseek_model` 配置，默认 `deepseek-flash`。

使用 DeepSeek `POST /chat/completions`，开启 `response_format: {"type":"json_object"}`、关闭思考、非流式调用、最多 4096 输出 token。仅接受完整结束（`finish_reason: "stop"`）的 JSON 对象。提示词说明资料内的指令不可执行，国家缺失不能猜测，缺失字段留空，并给出 JSON 示例。官方协议核对来源：[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。

验证通过供应商模拟响应进行，不发送真实地址或产生实际 DeepSeek 调用费用。
