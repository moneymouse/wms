# 预发环境 IP HTTPS 部署

原预发仓库直接升级为 `https://8.166.137.88:8081`，继续使用原来的
`wms_pre-nginx-1` 服务，不增加第二个仓库入口。MCP 地址是
`https://8.166.137.88:8081/mcp`；旧 HTTP 地址会在同一端口转到 HTTPS。
`wms_pre_tls` 只是证书、续期工具与账号状态目录，不是仓库应用或 Git 仓库。生产 `80` 端口仅提供已有静态目录中的 ACME
验证文件，不替换生产 Nginx 配置或重启生产容器。

使用 Let’s Encrypt 公信 IP 证书与 Certbot 5.8.0，可采用独立 Python venv
或官方 Docker 镜像。IP 证书使用
`shortlived` profile，有效期约 160 小时，必须保留自动续期。参见
[Let’s Encrypt IP 证书说明](https://letsencrypt.org/2026/03/11/shorter-certs-certbot/)
和 [Certbot 参数及续期说明](https://eff-certbot.readthedocs.io/en/stable/using.html)。

## 服务器目录和端口

- 部署目录：`~/wms_pre/wms_backend`。
- 证书、ACME 账号及续期状态：`~/wms_pre_tls/{letsencrypt,work,logs}`，权限
  `700`，与部署目录同级，避免被 `deploy_pre.sh` 的 `rsync --delete` 删除。
- HTTP-01 webroot：`~/wms/wms_frontend/build`，须能通过公网 `80` 端口访问
  `/.well-known/acme-challenge/` 文件；续期时继续保持此入口和目录可用。
- 阿里云安全组及服务器防火墙放行 TCP `8081`；TCP `80` 用于 CA 验证。
  后端、MCP 与数据库端口无需额外开放。

## 初次签发和配置

以下命令在服务器 SSH 用户下执行，该用户需要有 Docker 权限。证书写入采用
相同 UID/GID，续期也使用该用户，私钥不公开。

```bash
umask 077
mkdir -p ~/wms_pre_tls/{letsencrypt,work,logs}
mkdir -p ~/wms/wms_frontend/build/.well-known/acme-challenge
chmod 755 ~/wms/wms_frontend/build/.well-known \
  ~/wms/wms_frontend/build/.well-known/acme-challenge

docker run --rm --user "$(id -u):$(id -g)" \
  -v "$HOME/wms_pre_tls/letsencrypt:/etc/letsencrypt" \
  -v "$HOME/wms_pre_tls/work:/var/lib/letsencrypt" \
  -v "$HOME/wms_pre_tls/logs:/var/log/letsencrypt" \
  -v "$HOME/wms/wms_frontend/build:/var/www/acme" \
  certbot/certbot:v5.8.0 certonly \
  --webroot -w /var/www/acme --ip-address 8.166.137.88 \
  --preferred-profile shortlived --cert-name wms-pre-ip \
  --agree-tos --register-unsafely-without-email --no-eff-email --non-interactive
```

首次签发先在上述命令末尾追加 `--dry-run` 测试 CA 验证，成功后再执行不带
`--dry-run` 的命令。服务器不能拉取镜像时，可在本机预拉官方镜像并导入：

```bash
docker pull certbot/certbot:v5.8.0
docker save certbot/certbot:v5.8.0 | ssh Ali docker load
```

也可使用服务器现有 Python 3.11+ 创建独立 venv，从官方 PyPI 安装固定版本，
无需 sudo、系统 Python 包变更或 Docker daemon 重启：

```bash
python3 -m venv "$HOME/wms_pre_tls/certbot-venv"
"$HOME/wms_pre_tls/certbot-venv/bin/pip" install \
  --index-url https://pypi.org/simple certbot==5.8.0
"$HOME/wms_pre_tls/certbot-venv/bin/certbot" certonly \
  --config-dir "$HOME/wms_pre_tls/letsencrypt" \
  --work-dir "$HOME/wms_pre_tls/work" --logs-dir "$HOME/wms_pre_tls/logs" \
  --webroot --webroot-path "$HOME/wms/wms_frontend/build" \
  --ip-address 8.166.137.88 --preferred-profile shortlived --cert-name wms-pre-ip \
  --agree-tos --register-unsafely-without-email --no-eff-email --non-interactive
```

此方案同样先追加 `--dry-run` 检查，再正式签发。续期脚本会优先自动检测这个
venv；两种方式使用相同证书目录和 Nginx 配置。

若 Ubuntu 提示缺少 `ensurepip`，可在用户目录安装 virtualenv 后创建同一环境：

```bash
python3 -m pip install --target "$HOME/wms_pre_tls/venv-bootstrap" virtualenv
PYTHONPATH="$HOME/wms_pre_tls/venv-bootstrap" python3 -m virtualenv \
  --no-periodic-update --app-data "$HOME/wms_pre_tls/venv-cache" \
  "$HOME/wms_pre_tls/certbot-venv"
```

网络慢时可沿用项目的阿里云 PyPI 镜像，或预下载官方 wheel 后离线安装。

没有邮箱注册不会收到邮件提醒；以续期日志和证书到期时间检查运行情况。
签发后的固定路径为 `letsencrypt/live/wms-pre-ip/`。Nginx 挂载整个
`letsencrypt` 目录，保证 `live` 到 `archive` 的软链接在续期后继续生效。

编辑服务器上的 `~/wms_pre/wms_backend/PRE_BK.env`，保留现有随机会话密钥：

```env
OAUTH_ISSUER_URL=https://8.166.137.88:8081
MCP_PUBLIC_URL=https://8.166.137.88:8081/mcp
MCP_ALLOWED_HOSTS=8.166.137.88:8081
MCP_ALLOWED_ORIGINS=https://8.166.137.88:8081
OAUTH_ALLOW_LOCAL_HTTP=false
```

`OAUTH_SESSION_SECRET` 必须是至少 32 字符的随机值；不要提交实际密钥。
Origin 不带末尾 `/`。后端与 MCP 共用这个环境文件。

## 部署

Compose 需为 2.24.4 或更新版本，TLS overlay 使用 `ports: !override` 将原
`8081:80` 改为 `8081:443`，避免叠加第二个端口映射。

本机执行 `./deploy_pre.sh`。脚本发现有效证书文件后自动加载 TLS overlay、
启用 `mcp` profile，并在替换代理前运行 `nginx -t`。证书不存在时继续原有
HTTP 部署流程；证书不完整或 Nginx 配置检查失败时停止服务更新。

手动部署采用同样的 Compose 参数：

```bash
cd ~/wms_pre/wms_backend
docker compose -f docker-compose.pre.yml -f docker-compose.pre.tls.yml \
  --profile mcp run --rm --no-deps --entrypoint nginx nginx -t
docker compose -f docker-compose.pre.yml -f docker-compose.pre.tls.yml \
  --profile mcp up -d --build mysql backend mcp
docker compose -f docker-compose.pre.yml -f docker-compose.pre.tls.yml \
  --profile mcp up -d --no-deps --force-recreate nginx
```

只对 Nginx 强制重建，以更新被 rsync 替换的配置文件挂载；backend 和 MCP
由 Compose 检测镜像和环境变化。首次 MCP 部署仍需按 MCP 文档执行数据库迁移。
以后手动操作预发 Compose 时也要带上两个 `-f`，避免移除 HTTPS 映射。
如更换 IP，需重新签发证书并一起更新 Nginx 的 IP、HTTP 跳转地址和 OAuth 配置。

## 自动续期与检查

脚本 `scripts/renew_pre_tls.sh` 自动检测独立 venv，没有 venv 时使用 Docker
运行 Certbot，并防止并发执行；
证书成功续期后才执行 Nginx 检查和 reload。失败的 reload 标记会保留，供下次
运行重试。`PRE_TLS_DIR`、`PRE_TLS_WEBROOT`、`PRE_BACKEND_DIR` 和
`CERTBOT_IMAGE` 可覆盖默认值；`CERTBOT_BIN` 可指定其他 Certbot 可执行文件的
绝对路径。默认无需设置。

先测试续期及 reload hook：

```bash
~/wms_pre/wms_backend/scripts/renew_pre_tls.sh --dry-run
```

在同一 SSH 用户的 crontab 中追加以下行（保留已有任务）：

```cron
23 */6 * * * /home/tony/wms_pre/wms_backend/scripts/renew_pre_tls.sh >> /home/tony/wms_pre_tls/renew.log 2>&1
```

根据服务器实际 HOME 调整绝对路径。每 6 小时检查一次，仅在 Certbot 判断
需要续期时申请；日常查看 `~/wms_pre_tls/renew.log` 与 `logs/`。

Ali 已配置正式 IP 证书并验证公网信任链、HTTPS 发现接口与续期演练。
仓库和 MCP 共用原 8081 端口的 HTTPS 入口，旧 HTTP 地址自动转至 HTTPS；首次连接客户端
仍需使用 WMS 账号完成 OAuth 授权。

```bash
curl -I https://8.166.137.88:8081/
curl https://8.166.137.88:8081/.well-known/oauth-authorization-server
curl https://8.166.137.88:8081/.well-known/oauth-protected-resource/mcp
curl -i -X POST https://8.166.137.88:8081/mcp \
  -H 'Content-Type: application/json' -d '{}'
```

无需 `curl -k`；网页应返回 200，发现接口返回 JSON，未认证 MCP 返回 401 和
OAuth 发现信息。确认旧 `http://8.166.137.88:8081` 地址返回 308 并指向同端口 HTTPS，
HTTPS REST 未登录时正常返回 401。
