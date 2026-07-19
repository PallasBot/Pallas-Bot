# 单进程部署

单进程承载全部 Bot 能力。适用：本地开发、小规模自用、功能验证。

## 特点

| 项 | 说明 |
| --- | --- |
| 架构 | 单进程，无 hub/worker 拆分 |
| 依赖 | 不强制 Redis |
| 排障 | 协议端、Bot、扩展同进程，日志路径最短 |

## 部署检查

- [ ] `config/pallas.toml` 已配置 `superusers` 与数据库段
- [ ] WebUI 可访问：`http://<主机>:8088/pallas/`
- [ ] 协议端 WebSocket 指向当前进程
- [ ] 所需官方插件已安装并重启生效

## 启动与验证

```bash
cd /path/to/Pallas-Bot
uv run nb run
```

| 检查项 | 预期 |
| --- | --- |
| 进程日志 | 无数据库连接致命错误 |
| Health | `curl -s http://127.0.0.1:8088/pallas/api/health` 返回 JSON |
| 协议端 | 控制台显示账号在线 |
| 群内命令 | **牛牛帮助** 有响应 |

## 失败分支

| 现象 | 先查 |
| --- | --- |
| 启动即退出 | `pallas doctor`；数据库连通性与 `pallas.toml` |
| Health 拒绝连接 | `host`/`port`、防火墙、进程是否在跑 |
| QQ 在线无回复 | 协议端 `ws_url`、是否连到当前进程 |
| 插件无功能 | 是否重启；`local/plugins/` 同名覆盖 |

## 相关文档

- [标准部署](/deploy/deployment)
- [Docker 部署](/deploy/docker)
- [排障](/maintainer/operate/troubleshooting)
