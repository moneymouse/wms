# API v1.19 — MCP 与 OAuth 2.1

WMS 新增独立远程 MCP 服务，复用现有 WMS 账号、业务权限和数据库。
现有 REST 接口和 `x-token` 登录保持兼容；MCP 只接受 OAuth Bearer token。

WorkBuddy 用户接入使用 `integrations/workbuddy/wms-mcp.zip` 技能包。
包内 `SKILL.md`、接入说明及标准库 Python 客户端支持用户独立 OAuth 授权，
以实时工具 Schema 调用业务；不包含共享账号、密钥或令牌。
客户端的模拟 HTTP 验证可执行
`python -m unittest discover -s integrations/workbuddy/tests -v`。

## 服务与工具

客户端连接地址是配置的 `MCP_PUBLIC_URL`，例如 `https://wms.example.com/mcp`。
传输采用 Streamable HTTP，使用 MCP Python SDK 2.2.0。客户端通过标准
`tools/list` 发现工具，通过 `tools/call` 调用；没有额外 GET 工具列表接口。

| 工具 | 业务接口 | 参数 | 所需 scope |
| --- | --- | --- | --- |
| `create_order` | `POST /api/create` | `order` 业务对象、`idempotency_key` | `orders:create` |
| `list_orders` | `GET /api/orders` | `p=1,s=30,sf=create_date,so=1,q=""` | `orders:list` |
| `get_order` | `GET /api/orders/<uid>` | `uid` | `orders:read` |
| `create_packing_list` | `POST /api/packing-list` | `mark` 或 `list_number`、可选 `customer_id/photos`、`idempotency_key` | `packing_lists:create` |

所有 MCP 请求还需要基础 `mcp` scope。`tools/list` 返回四个工具的输入和输出
Schema；工具调用根据当前数据库角色和授权 scope 共同决定能否执行。订单列表
沿用全部未归档订单的可见范围，保持搜索、排序、分页和每页最多 200 条的限制。

订单创建字段沿用现有接口，包括客户、收件人、地址、运输方式、重量、业务员
`salesman_id` 和可选初始 `quote`。操作人、装箱单创建者和审计身份来自 OAuth
用户，不能由工具参数提供；内部 UID、归档和创建时间等字段不可写。
装箱单只创建草稿表头，不创建箱子、不绑定订单；照片参数是已有图片地址。

结果提供 `structuredContent` 和文本摘要，业务字段保留 REST JSON 响应格式。
业务失败使用 `isError=true`；订单不存在或已归档明确返回“订单不存在”。

### 创建与重试

两个创建工具的 `idempotency_key` 都是必填。一次逻辑创建生成一个键；网络失败
或响应丢失后，使用原键和原参数重试。新的逻辑创建必须使用新的键。

唯一范围是用户、OAuth 客户端、工具和键。同键同参数返回原结果，同键不同参数
返回冲突。成功记录不会自动过期后重新执行。MCP 订单创建将收件人、订单 V1、
初始报价、业务审计和幂等结果放在同一事务中，任何一步失败全部回滚。
原网页 REST 创建仍保留已有的“订单成功、报价失败”响应语义。

调用示例（省略协议版本及认证头，由客户端 SDK 管理）：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "create_order",
    "arguments": {
      "idempotency_key": "intake-20261005-001",
      "order": {"order_id": "EXAMPLE-001", "receiver": "示例收件人"}
    }
  }
}
```

## OAuth 授权

| 路径 | 用途 |
| --- | --- |
| `GET /.well-known/oauth-protected-resource/mcp` | MCP 资源及授权服务器发现 |
| `GET /.well-known/oauth-authorization-server` | OAuth 能力和端点发现 |
| `/oauth/login` | WMS 账号浏览器登录 |
| `/oauth/authorize` | 授权码请求及用户同意/拒绝 |
| `POST /oauth/token` | 授权码兑换和刷新 |
| `POST /oauth/register` | DCR 兼容注册 |
| `POST /oauth/revoke` | 撤销令牌 |

支持公开 HTTPS 客户端元数据文档 CIMD，并保留 DCR 接入方式。
授权页展示客户端来源、回调地址及请求权限，用户可以拒绝或缩小授权。
没有传 scope 时默认请求全部支持的 scope；显式 scope 只授权请求中的项目。
仅请求 `mcp` 可发现工具；业务工具需要表中对应的额外 scope。

浏览器登录和授权页使用安全会话 Cookie 与 CSRF 表单校验。已登录会话的
CSRF nonce 在多个授权页之间保持稳定，重新登录时重建会话；失效表单仍返回
HTTP 403，并显示可重新提交的页面，保留用户已选择的权限。授权页的 CSP
`form-action` 仅额外放行已校验回调地址的 origin，避免 Chrome 阻止授权后的
跨站回调；未注册或未通过校验的地址不会扩展该白名单。

使用 Authorization Code + PKCE，必须是 `S256`。授权请求、令牌兑换和刷新
均需提供与 `MCP_PUBLIC_URL` 一致的 `resource`。授权响应带固定 issuer 的
`iss`。回调必须匹配客户端登记值，生产回调使用 HTTPS；本地原生客户端允许
标准 loopback 回调。

访问令牌默认 15 分钟，授权码 5 分钟，刷新令牌 30 天。令牌使用随机 opaque
值，数据库只存哈希；刷新时轮换，旧刷新令牌重放会撤销整个令牌家族。
账号被拒绝、删除或角色发生变化后，后续调用读取实时状态并应用当前权限。

未认证或令牌失效返回 HTTP 401 和 `WWW-Authenticate` 发现信息；scope 不足
返回 HTTP 403 和所需 scope。业务角色拒绝不会因为重新申请 scope 而放宽。

## 配置与部署

参考 `MCP.env.example`，将生产值加入 backend 与 MCP 共用的 `BK.env`；
预发布加入 `PRE_BK.env`。issuer、resource 和 Cookie 密钥都显式配置，
不从请求的 Host 推导。未配置或配置不合法时，Flask 记录原因并停用 OAuth，
OAuth 接口返回 503，已有 REST 服务仍可启动。独立 MCP 服务仍严格拒绝不合法
的配置，不会因 REST 恢复而放宽 HTTPS、resource 或令牌校验。

1. 安装 `requirement.txt` 中的依赖；Docker 镜像包含 Authlib 1.8.0、MCP 2.2.0
   和 Uvicorn。迁移由 backend 统一执行，MCP 容器不运行管理员初始化或备份。
2. 在已确认的数据库上执行 `alembic upgrade head`，新增 OAuth 与幂等表。
   生产需要按现有流程明确启用迁移，不能跳过新表。
3. 配置真实 HTTPS 入口及 Nginx 路由，然后启用 Compose 的 `mcp` profile：

```sh
docker compose --profile mcp up -d --build backend mcp nginx
```

预发布使用 `-f docker-compose.pre.yml`；测试使用
`-f docker-compose.test.yml` 及 `backend_test/mcp/nginx_test` 服务名。
开发配置的 MCP 端口只映射到 `127.0.0.1:8000`。

Nginx 将 `/mcp` 和资源发现转发给 MCP，`/oauth/` 和授权服务器发现转发给
Flask。MCP 上游使用 Docker 动态 DNS，因此未启动可选 MCP 容器时不影响
现有 REST 的 Nginx 启动。正式 OAuth 必须部署 HTTPS；内部 TLS 卸载后，
Authlib 使用配置的固定公共 issuer 构造协议地址。

本地可在明确启用 `OAUTH_ALLOW_LOCAL_HTTP=true` 后使用 loopback HTTP issuer
及 MCP URL。不能将该开关用于公网 HTTP。停止 MCP 服务即可停用工具入口，
保留数据库表和已有 REST 服务。

## 验证

在 WMS Python 环境内安装依赖后执行：

```sh
python -m pytest --confcutdir=tests/oauth tests/oauth
python -m pytest --confcutdir=tests/mcp tests/mcp
```

测试覆盖真实 HTTP 发现、授权及工具调用，不能用绕过 HTTP 鉴权的内存 MCP
连接替代。专用 MySQL 并发测试使用 `MCP_CONCURRENCY_DATABASE_URL`，数据库
名称必须包含 `test`，并先执行迁移。例如使用一次性测试库：

```sh
export MCP_CONCURRENCY_DATABASE_URL='mysql+pymysql://test_user:test_password@127.0.0.1:3307/wms_mcp_test'
python -m pytest --confcutdir=tests/oauth tests/oauth/test_mysql_concurrency.py
python -m pytest --confcutdir=tests/mcp tests/mcp/test_mysql_concurrency.py
```

本次验证：OAuth 83 项、MCP HTTP/幂等/端到端 21 项、共享业务事务 11 项，
以及 MySQL 8.4 的 5 项并发用例全部通过；完整 Alembic 迁移链已在一次性
MySQL 库执行成功，三份 Nginx 配置通过容器内语法检查。
既有鉴权、订单与装箱流程回归同时通过。OAuth 浏览器回调修复另通过真实
Chrome 的三种跨源表单跳转验证；WorkBuddy 技能客户端通过 12 项模拟 HTTP
测试，并在预发完成用户亲自登录授权、四工具发现、订单分页和详情查询。
