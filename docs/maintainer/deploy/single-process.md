# 单进程部署

单进程承载消息主路径，并自动维护 **work aux**；本机 Embedding 也可另起 `bot_embed`。适合本地开发、自用与默认生产路径；多数站点先用本形态，仅在验证过瓶颈或需要强隔离时再上 [分片](sharded.md)。

## 特点

| 项 | 说明 |
| --- | --- |
| 架构 | 单 ingress 进程 + 一个数据库 outbox 消费者；不占分片心智 |
| 依赖 | work aux 不强制 Redis；本机 Embedding 需要 Redis + embed 辅进程 |
| 排障 | 主日志、`data/pallas_work/logs/work.log` 与可选 `data/pallas_embed/logs/` |

## 部署检查

- [ ] `config/pallas.toml` 已配置 `superusers` 与数据库段
- [ ] WebUI 可访问：`http://<主机>:8088/pallas/`
- [ ] 协议端 WebSocket 指向当前进程
- [ ] 所需官方插件已安装并重启生效

## 启动与验证

```bash
cd /path/to/Pallas-Bot
uv run pallas                 # 或 uv run pallas run unified
uv run pallas status
uv run pallas logs            # Bot + 可选 embed 辅进程
```

| 检查项 | 预期 |
| --- | --- |
| 进程日志 | 无数据库连接致命错误 |
| Health | `curl -s http://127.0.0.1:8088/pallas/api/health` 返回 JSON |
| 协议端 | 控制台显示账号在线 |
| 群内命令 | **牛牛帮助** 有响应 |
| 后台任务 | `status` 中 work 辅进程为运行中 |
| 本机 Embedding | `status` 中 embed 辅进程为运行中（需 Redis + `local`） |

## 失败分支

| 现象 | 先查 |
| --- | --- |
| 启动即退出 | `pallas doctor`；数据库连通性与 `pallas.toml` |
| Health 拒绝连接 | `host`/`port`、防火墙、进程是否在跑 |
| QQ 在线无回复 | 协议端 `ws_url`、是否连到当前进程 |
| 插件无功能 | 是否重启；`local/plugins/` 同名覆盖 |

## 何时改看分片

多个 Bot 账号同时在线、单进程已卡顿，或需要独立 worker 协调时，再阅读 [分片部署](sharded.md)。完整源码步骤见 [标准部署](/deploy/deployment)。

## 相关文档

- [标准部署](/deploy/deployment)
- [Docker 部署](/deploy/docker)
- [排障](/maintainer/operate/troubleshooting)
- [运维入口](/maintainer/quickstart)
