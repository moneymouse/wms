# WorkBuddy 接入与分发

## 安装 Skill

将 `wms-mcp.zip` 发给用户。在 WorkBuddy 的技能管理入口选择“添加技能”→
“上传技能”，导入并启用。不同版本可能将入口放在“专家·技能·连接器”或“技能”中。
若导入器要求选择目录，解压后选择包含 `SKILL.md` 的 `wms-mcp` 目录。

官方说明：[WorkBuddy 技能](https://cloud.tencent.com/document/product/1831/134432)。
包内不含账号、客户端密钥或令牌；每个用户首次使用都要独立授权。

## 方式一：原生 MCP OAuth

在 WorkBuddy 侧边栏“插件”→“MCP 服务器”→“配置 MCP”中添加服务。
英文版入口可能是 Settings → MCP → Add MCP Server。

填写：

| 项目 | 值 |
| --- | --- |
| 显示名称 | `wms-pre` |
| 服务 URL | `https://8.166.137.88:8081/mcp` |
| 传输 | Streamable HTTP / HTTP |
| 认证 | OAuth，浏览器登录 |

完成弹出的 WMS 登录和授权页面。只查询时保留 `mcp`、`orders:list`、
`orders:read`；创建订单增加 `orders:create`，创建装箱单增加
`packing_lists:create`。客户端未提供权限输入框时，在 WMS 授权页选择。
授权页的回调地址应属于当前客户端，服务来源应为预发 WMS。

连接后调用工具发现；应看到四个业务工具。再请求“查询最新三条订单，
不要创建数据”验证业务权限。原生客户端负责保存和刷新令牌。

用户级 MCP 配置在 `~/.workbuddy/mcp.json`，项目级在
`<项目目录>/.workbuddy/mcp.json`。优先通过当前版本的配置界面添加，
合并已有服务器配置，保留其他服务。

来源：[中文 MCP 配置指南](https://www.codebuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)、
[英文 MCP OAuth 说明](https://www.codebuddy.ai/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/MCP-Guide)。
官方说明支持 OAuth 自动刷新；实际客户端版本仍须通过登录和工具调用验证。

## 方式二：仅通过 Skill 的 Python 客户端

原生 MCP 尚未配置或客户端 OAuth 不兼容时，使用包内脚本。
要求本机 Python 3.10+，无需安装第三方包。以下命令从 Skill 目录运行；
在其他工作目录运行时使用脚本的实际绝对路径并正确引用含空格的路径。
Windows 可将 `python3` 换成 `py -3`。

```sh
python3 scripts/wms_mcp.py login
python3 scripts/wms_mcp.py tools-list
python3 scripts/wms_mcp.py call list_orders --arguments '{"p":1,"s":3}'
python3 scripts/wms_mcp.py status
```

`login` 打开系统浏览器；用户亲自登录、确认授权后，浏览器返回本机
`127.0.0.1` 临时回调地址。若未自动打开浏览器，打开命令输出的授权链接。
可用 `--no-browser` 仅输出链接。命令需保持运行直到回调完成。
默认申请只读权限；需要创建装箱单时，仅增加该任务的权限：

```sh
python3 scripts/wms_mcp.py login --scope 'mcp packing_lists:create'
```

创建订单使用 `--scope 'mcp orders:create'`；任务需要查询时同时增加
`orders:list orders:read`。确实需要全部四种能力时才使用 `login --all-scopes`。

Windows 或复杂业务参数优先写入 UTF-8 JSON 文件，避免不同终端的引号差异。
例如创建 `query.json`，内容为 `{"p":1,"s":3}`，然后执行：

```text
py -3 scripts/wms_mcp.py call list_orders --arguments-file query.json
```

首次授权后脚本用私有缓存保存令牌并自动刷新，原生 WorkBuddy 与脚本使用
各自的 OAuth 客户端和凭据。不要在两种连接之间重试状态不确定的创建操作，
因为幂等范围包含客户端 ID。

退出并撤销脚本授权：

```sh
python3 scripts/wms_mcp.py logout
```

令牌缓存不属于 Skill 内容，不随 ZIP 分发。Windows 用户需确保缓存目录仅
当前用户可读取。命令输出中的业务数据按用户任务需要展示，令牌不能展示。

## 发现与故障定位

- 资源发现：`https://8.166.137.88:8081/.well-known/oauth-protected-resource/mcp`。
- 授权服务器发现：`https://8.166.137.88:8081/.well-known/oauth-authorization-server`。
- issuer：`https://8.166.137.88:8081`，resource：完整的 `/mcp` URL。
- `tools/list` 是带令牌的 MCP JSON-RPC 方法，不是 `GET /mcp/list`。
- 未登录的 `/mcp` 返回 401 和 `WWW-Authenticate` 是正常行为。
- 浏览器登录被拒绝：检查 WMS 账号密码与审核状态。
- 403 `insufficient_scope`：重新授权对应 scope；业务角色拒绝应联系 WMS 管理员。
- TLS 报错：检查系统时间、证书信任和服务证书；不要使用 `-k` 或关闭校验。
- 公网地址应使用 HTTPS；`http://8.166.137.88:8081` 不是 MCP 配置地址。

给用户的首次对话示例：

> 使用 wms-mcp Skill 接入迅达 WMS 预发，完成我的账号授权，列出工具并查询最新三条订单。
