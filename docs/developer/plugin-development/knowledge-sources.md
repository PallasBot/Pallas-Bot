# 知识源与本地 ingest

| 机制 | 入口 |
| --- | --- |
| 插件声明 | `PluginMetadata.extra['knowledge_sources']` |
| 本地目录 | `data/pallas_knowledge*.md` / `.jsonl` |

Bot 在 LLM 闲聊前统一检索并注入 system prompt。无 LLM 时知识源不参与注入。

## 官方参考

本体 [`packages/llm_chat`](https://github.com/PallasBot/Pallas-Bot/tree/main/packages/llm_chat/__init__.py) 与内置 FAQ（`pallas.bot_faq`）可作为对照。

## 插件声明示例

```python
from pallas.product.llm.knowledge.declare import knowledge_source_row

extra={
    "knowledge_sources": [
        knowledge_source_row(
            source_id="my_plugin.faq",
            title="插件 FAQ",
            description="本插件常见问题",
            chunks=[
                {
                    "title": "用法",
                    "content": "发送 xxx 触发功能。",
                    "keywords": "用法,帮助,怎么用",
                },
            ],
        ),
    ],
}
```

## 本地目录 ingest

| 项 | 说明 |
| --- | --- |
| 路径 | `data/pallas_knowledge*.md` 或 `.jsonl` |
| 开关 | `LLM_KNOWLEDGE_FILE_INGEST_ENABLED`（默认开） |
| source_id | `pallas.file_ingest` |
| Markdown | 按 `#` 标题切块 |
| JSONL | 每行一条 JSON 对象，字段包括 `title`、`content`、`keywords` |

示例见仓库内 `data/pallas_knowledge/example.md`，例如：

```jsonl
{"title": "示例标题", "content": "这是内容示例。", "keywords": "关键字1,关键字2"}
```

## 知识源 vs LLM Tool

| 场景 | 推荐 |
| --- | --- |
| 短 FAQ、规则、产品说明 | `knowledge_sources` / 本地目录 + prompt 注入 |
| 参数化查询、大 KB | `llm_tools` |

## 治理与检索

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_KNOWLEDGE_SOURCES_ENABLED` | 开 | 总闸 |
| `LLM_VECTOR_RETRIEVE` | `hybrid` | `hybrid` / `keyword` / `embedding`；向量失败回落关键词 |
| `LLM_EMBEDDING_MODEL` | `stub` | Bot 内核本地 hash stub 标识；无需 AI 仓 |
| `LLM_KNOWLEDGE_TOP_K` | `3` | 注入块数上限 |

读取受 `memory_governance.can_read_generic_knowledge()` 门控。运维视角见 [LLM 与 AI](/maintainer/operate/llm-and-ai)。
