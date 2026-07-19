# 本地知识目录

将 Markdown（`.md`）或 JSONL（`.jsonl`）放在本目录（可含子目录），Bot 会在 LLM 闲聊前检索并注入。

- 开关：`LLM_KNOWLEDGE_FILE_INGEST_ENABLED`（默认开）
- 说明：[Developer · 知识源](../../docs/developer/plugin-development/knowledge-sources.md)

本目录内容默认不进 Git（见同级 `.gitignore`）；`README.md` 与 `example.md` 可保留作样例。
