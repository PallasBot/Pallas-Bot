# 插件文档与文档站同步

| 角色 | 路径 |
| --- | --- |
| 权威正文 | `docs/plugins/<name>/README.md` |
| 文档站 | `Pallas-Bot-Docs/src/plugins/<name>.md` |

同步命令（在主仓根）：

```bash
uv run python tools/scripts/sync_docs_to_web.py --plugins-only
```

扁平 `docs/plugins/<name>.md`：正式插件仅为指向 `README.md` 的指针；`ollama.md` / `pallas_*.md` 等为归档 stub。
