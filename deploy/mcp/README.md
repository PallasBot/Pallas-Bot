# 独立 MCP 容器

该容器只启动方舟/PRTS HTTP MCP，不启动 Bot、数据库或媒体服务。应与生产 Bot 使用独立数据目录；不要挂载控制台凭据或群聊数据库。

## 构建

从仓库根目录准备 `uv.lock`，再构建：

```bash
uv lock
docker build -f deploy/mcp/Dockerfile -t pallas-mcp:<build-id> .
```

生产构建应将 `UV_IMAGE`、`PYTHON_IMAGE` 两个 build arg 固定为已验证的镜像 digest，并记录源码快照、锁文件与最终镜像 ID。内存较小的出口机不承担镜像构建或资料处理。
运行直接使用已安装的 `.venv/bin/python`，不会在只读文件系统上再次执行 `uv sync`。

## 启动

将 `compose.env.example` 复制到部署目录的 `compose.env`，设置已验证镜像、准确域名和独立数据目录。该文件不是凭据库；不要把明文 MCP Key 写入它。
预先创建两个绑定目录，归属 UID/GID `10001:10001`；凭据所在数据目录权限应为 `0700`。资料建议落在空间充足的数据盘，并在更新前检查剩余空间。

```bash
docker compose --env-file /path/to/compose.env -f deploy/mcp/compose.yml up -d
docker compose --env-file /path/to/compose.env -f deploy/mcp/compose.yml exec mcp \
  /app/.venv/bin/python -m pallas.console.cli.main mcp corpus status
```

默认仅将端口发布到宿主回环地址，独立身份运行、只读根文件系统、限定 CPU/内存/进程数。healthcheck 的 `401` 只证明传输与认证入口就绪，不证明资料完整，仍须执行授权查询验收。该 `401` 判据仅适用于 private 默认；公共只读模式不再返回 401，应改用一次有效的无鉴权 JSON-RPC ping / initialize（`POST /mcp` 返回 200）作为健康检查。

PRTS 初次同步明确限定为 `references`，在受限容器内显式执行 `mcp corpus update`。需要扩展 pack 时先评估内存、磁盘和内容使用条件。同步结构化游戏表仍使用架构文档列出的既有同步入口。
缓存与累计解压各默认 64 MiB，这是原始字节预算，不是 Python RSS 保证；超预算会失败，而容器硬内存限制单独生效。预算配置修改后须重启新 MCP 容器，不需要重启 Bot。

## HTTPS 与隧道

- TLS 由反向代理终止，后端只允许准确 Host；不得直接公开容器端口。
- 跨机器出口可使用独立 SSH 反向隧道，严格验证主机身份，并确认远端仅监听回环地址（如 `-R 127.0.0.1:8765:127.0.0.1:8765`，服务端 `GatewayPorts=no`）。不需要停用、重启或修改现有 SSH 服务，也不要改动旧 frp 实例；不要把默认不验证服务端身份的 frp TLS 连接当作已验证的可信传输。
- 反代仅路由准确 `/mcp`，HTTP 端口只做 ACME 验证与 HTTPS 跳转。compose 默认不提供匿名查询；若确认要以公共只读方式对外，需在独立部署的 override command 中显式追加 `--public-readonly` 并调整应用全局 rate（公共共享预算），不要改动本 compose 默认值。此时经隧道后端看不到真实 IP，反代必须对该 MCP vhost 自行按 IP 限流（不信任 `X-Forwarded-For`）。
- 应用默认关闭 access log；反代也关闭该入口的请求行日志，避免调用方误将密钥写入 URL 后落日志。私有模式调用方仍必须使用 Authorization Bearer Header。

## 对应源码与回滚

对外运行修改版时，需向使用者提供与实际镜像一致的对应源码。静态源码归档应包含构建文件、锁文件及必要说明，不得包含 `.git`、环境配置、凭据、运行资料或 `docs/agent/`。
将归档以不可变的版本地址通过 HTTPS 提供，并在 `MCP_SOURCE_URL` 设置该地址；compose 将其传给 `--source-url`。SDK 初始化说明会提示该地址，反代可同时添加源码 Link Header。不要将旧镜像的源码地址覆盖成新代码。

切换前保留前一镜像、运行配置、对应源码归档及反代配置备份。失败时恢复成组物料并 reload 反代；不得删除社区数据库、旧 Bot 数据或其他容器。
密钥按调用方单独签发、仅显示一次，测试身份验收后撤销。静态 Bearer 不是 OAuth 登录；单进程限流不等于多副本配额。
