# 插件文档与文档站同步

| 角色 | 路径 |
| --- | --- |
| 权威正文 | `docs/plugins/<name>/README.md`（无目录时为扁平 `docs/plugins/<name>.md`） |
| 文档站 | `Pallas-Bot-Docs/src/plugins/<name>.md` |

同步命令（在主仓根）：

```bash
uv run python tools/scripts/sync_docs_to_web.py --plugins-only
```

扁平 `docs/plugins/<name>.md`：若同名目录已有 `README.md`，扁平文件仅为指针。`ollama.md` / `pallas_*.md` / `community_stats.md` 等为归档 stub。
