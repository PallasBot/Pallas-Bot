# 日志位置与导出

查运行问题时，先确认部署形态（默认 **unified + 可选 aux** / 分片 / Docker），再按下表找日志。日常优先：

```bash
uv run pallas logs          # 默认 Bot + embed 辅进程；分片时给 hub
uv run pallas logs -f       # 实时跟随主日志（终端染色；后台运行在前台观测；Ctrl+C 退出）
uv run pallas logs -f --all # 实时跟随主日志 + 全部辅进程日志
uv run pallas status
```

更广的排障顺序见 [排障](troubleshooting.md)。

## 落盘位置

| 场景 | 位置 |
| --- | --- |
| unified（默认） | Bot 业务日志 `data/bot/nonebot_*.log`（消息实例持续写入）；`data/pallas_unified/logs/bot_*.log` 为启动器捕获 stdout，仅后台运行时产生 |
| embed 辅进程 | `data/pallas_embed/logs/embed.log`（本机 Embedding + Redis 时） |
| 分片（进阶） | `data/pallas_shard/logs/hub.log`、`worker-*.log`，以及同目录 bootstrap / archive |
| 控制台实时 | 内存环 + 上述文件尾；WebUI「运行日志」页 |
| Docker | 数据卷内对应 `data/`（具体挂载以 Compose 为准，常见为 `./pallas-bot/data`） |

默认排障跟 **unified Bot 日志**；语义/向量异常再看 embed 辅进程。分片故障优先查 hub，需要账号级再打开对应 `worker-*.log`，不要一上来扫全部分片文件。

## 控制台查看与导出

1. 打开 **`/pallas/` → 运行日志**。
2. 按范围（全部 / WebUI / 协议）、分片来源、级别与关键词筛选。
3. 点 **导出**：下载当前视图（结构化或原始行），文件名形如 `pallas-logs_{scope}_{source}_{YYYYMMDD-HHMM}.txt`。

浏览器导出在 Docker 下同样落到你本机；不依赖容器内另开 shell。

![网页控制台运行日志：按结构化级别、范围和关键词筛选后导出](/assets/webui-logs.png)

## API / curl（含 Docker）

与页面相同筛选参数：

```bash
# 需已登录控制台会话，或按你环境的鉴权方式带 Cookie / Token
curl -fsS -o pallas-logs.txt \
  -H "Cookie: …" \
  "http://127.0.0.1:<port>/pallas/api/logs/export?n=500&scope=all&source=all"
```

容器侧也可用 `docker compose logs pallasbot` 看编排 stdout；完整落盘仍以卷内 `data/` 为准。

## 相关

- [排障](troubleshooting.md)
- [WebUI 运维](webui.md)
- 开发者联调：[WebUI 前端开发](/developer/webui)
