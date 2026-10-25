# pre 分支自动部署

推送到 `pre` 分支后，`.github/workflows/deploy-pre.yml` 在 GitHub Ubuntu runner
上检出该次提交、安装 Node.js 22 和前端依赖，通过公网 SSH 连接
`agent@8.166.137.88:22`，然后在仓库根目录执行：

```bash
bash deploy_pre.sh --host wms-pre --remote-dir "$PRE_DEPLOY_DIR"
```

`deploy_pre.sh` 在 runner 构建前端，经 rsync 同步到服务器，再通过 SSH 执行
Docker Compose。默认不迁移数据库，保留脚本已有的预发 TLS/MCP 检测逻辑。
部署任务串行执行，新推送不会中断正在运行的部署；连续多次推送时 GitHub
可能以最新任务替换尚未开始的排队任务。

## 首次配置

在仓库 **Settings → Secrets and variables → Actions** 中配置以下项目。
ChatGPT 云环境中的密钥不会自动同步到 GitHub Actions。

### Repository secrets

| 名称 | 内容 |
| --- | --- |
| `PRE_SSH_PRIVATE_KEY` | `agent` 用户的完整、无口令 SSH 私钥；使用实际私钥，不是代理占位符 |
| `PRE_SSH_KNOWN_HOSTS` | 可选：已核验的服务器 SSH 主机公钥，采用 OpenSSH `known_hosts` 格式 |

默认只需配置 `PRE_SSH_PRIVATE_KEY`。没有配置 `PRE_SSH_KNOWN_HOSTS` 时，
工作流通过 `StrictHostKeyChecking=accept-new` 自动信任首次连接的主机公钥，
服务器预检成功后，将 `known_hosts` 单独保存到 Actions 缓存。后续部署按主机和端口
恢复同一份记录，并使用严格主机校验；指纹发生变化时停止部署，不自动覆盖旧记录。
私钥和 SSH 配置不会进入缓存。每次预检成功后都会在 Actions 日志中输出主机指纹。

GitHub runner 本身不会跨任务保留文件；这里的持久化依赖 Actions 缓存。缓存被清理、
过期或主机/端口改变后，会重新进行首次信任，因此这种方式不能替代预先核验服务器身份。
服务器合法更换主机公钥后，先通过可信渠道核验新指纹，再在仓库的
**Actions → Caches** 中删除对应的 `wms-pre-host-key-v1-主机-端口` 缓存后重新运行。

若希望从第一次连接就校验已知公钥，仍可配置可选的 `PRE_SSH_KNOWN_HOSTS`；
配置后直接使用它进行严格校验，不读取或写入上述缓存。
可以从已核验服务器身份的电脑取得 `known_hosts` 记录：

```bash
ssh-keygen -F 8.166.137.88 -f ~/.ssh/known_hosts
```

把有效的主机公钥记录存入 `PRE_SSH_KNOWN_HOSTS`。非默认端口的记录应对应
`[8.166.137.88]:端口`。此时即使缓存不存在，也不会自动信任未知公钥。

### Repository variables

| 名称 | 默认值 / 要求 |
| --- | --- |
| `PRE_DEPLOY_DIR` | 默认 `/home/agent/wms_pre`，可设置为其他已有预发目录的绝对路径 |
| `PRE_SSH_HOST` | 默认 `8.166.137.88`（公网地址，无需 VPN） |
| `PRE_SSH_USER` | 默认 `agent` |
| `PRE_SSH_PORT` | 默认 `22` |

目录必须以 `/wms_pre` 结尾，且只包含字母、数字、下划线、连字符和斜杠。
默认部署到 `agent` 用户的 `/home/agent/wms_pre`。请确保 `agent` 能读写该目录并运行
Docker。仓库变量优先于默认值；若 `PRE_DEPLOY_DIR` 仍指向旧目录
`/home/tony/wms_pre`，需将其改为新目录，或删除该变量以使用默认值。

从旧目录迁移时，先由管理员完成预发环境重置、运行时配置和数据同步、目录权限调整，
再合入新默认目录的变更或向 `pre` 推送，避免在新目录尚未准备好时触发部署。
仅上传源码和 `wms_frontend/build` 不会切换运行中的服务，也不会搬迁或重置数据库。
MySQL 使用 Compose 项目 `wms_pre` 的命名卷；是否保留或重置数据由管理员处理。
`PRE_DB.env`、`PRE_BK.env`、`env.toml` 以及日志、上传文件、历史数据和备份不会由
代码同步覆盖，需按需迁移到新目录。

## 服务器要求

- 已存在预发目录，SSH 登录用户对其有读写权限。
- `wms_backend/PRE_DB.env`、`PRE_BK.env` 和 `env.toml` 已配置且可读。
- 已安装 rsync、Docker 和 Docker Compose，SSH 登录用户可非交互运行 Docker。
- 使用 TLS overlay 时，Docker Compose 需支持 `!override`（2.24.4 或以上）。
- TLS 状态保存在部署目录同级的 `wms_pre_tls`，默认是 `/home/agent/wms_pre_tls`。
  迁移时需同步旧 `/home/tony/wms_pre_tls` 中的证书、ACME 状态及续期配置，并更新
  续期任务中的绝对路径。`agent` 必须能遍历证书路径并确认 `fullchain.pem`、`privkey.pem`
  存在；证书目录放在部署树外，避免被代码同步删除。
- SSH 公钥已加入登录用户的 `authorized_keys`。
- 公网 SSH 端口允许 GitHub runner 访问（默认 TCP 22）。

工作流在 rsync 之前检查目录、配置文件与 Docker 权限；配置缺失时提前失败。
已有 TLS 状态目录但证书不完整或不可访问时也会停止，防止误判为 HTTP 环境。
新目录同级没有 `wms_pre_tls` 时部署脚本会使用 HTTP 配置；需要 HTTPS/MCP 的环境
应先准备好该目录，旧用户目录中的证书不会自动沿用。
私钥仅写入 runner 临时目录，不进入仓库，也不会被部署脚本同步到服务器。
构建沿用手动执行脚本的行为：CRA 警告不会被 `CI=true` 提升为错误，实际构建错误
仍会中止部署。

配置完成后推送到 `pre`，在仓库 **Actions → Deploy pre** 查看结果。
不要向 `main` 推送来触发部署：此工作流仅监听 `pre`。
