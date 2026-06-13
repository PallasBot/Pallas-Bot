# 消息审查（message_scrub）

复读**学习**与做梦**采集/漂流**前统一过滤入站消息：命中规则的内容不入库、不参与后续逻辑。不配任何项时行为与过去一致。

实现：`src/features/message_scrub/`。

## 配置

| 项 | 说明 |
| --- | --- |
| WebUI | **通用配置 → 消息审查与入站过滤** |
| 落盘 | `data/pallas_config/webui.json` |
| 生效 | 保存后 hub 热重载；分片 worker 按磁盘 mtime 自动重读 |
| 启用 | 新部署默认不启用；`uv sync --extra message-scrub` + `apply_deploy_profile.py message-scrub`，或设 `PALLAS_MESSAGE_SCRUB_ENABLED=true` |

### 常用配置键

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `PALLAS_INBOUND_FILTER_SUBSTRINGS` | 空 | 英文逗号分隔关键词，命中即拦 |
| `PALLAS_SCRUB_LEXICON_PATH` | 空 | 本地词表 txt（UTF-8，一行一词） |
| `PALLAS_SCRUB_LEXICON_EXTRA` | 空 | 追加词，逗号分隔 |
| `PALLAS_SCRUB_REVIEW_PROVIDERS` | 自动 | 远程审查顺序：`baidu`、`json_http` 等 |
| `PALLAS_SCRUB_BAIDU_API_KEY` / `SECRET` | 空 | 百度内容审核密钥 |
| `PALLAS_SCRUB_API_URL` | 空 | 自建审查 HTTP 接口 |
| `PALLAS_INBOUND_FILTER_API_FAIL_OPEN` | 放行 | 远程失败时：`1` 放行，`0` 当拦 |

完整字段见 WebUI 或 [`config.py`](../../../src/features/message_scrub/config.py)。

## 使用场景

| 目标 | 做法 |
| --- | --- |
| 不用审查 | 保持默认即可 |
| 拦固定说法 | 配关键词子串 |
| 本地词表 | 准备 txt → 设 `PALLAS_SCRUB_LEXICON_PATH`；改词表内容一般无需重启 |
| 百度审核 | 填 API Key + Secret Key |
| 自建网关 | 设 `PALLAS_SCRUB_API_URL`；约定 `POST` JSON，`blocked: true` 表示拦截 |
| 本地 + 远程 | 可同时启用；顺序由 `PALLAS_SCRUB_REVIEW_PROVIDERS` 控制，默认先百度再自建 |

### 词表文件

UTF-8 文本，一行一词；`#` 开头为注释。相对路径相对于 Bot 工作目录，不确定时用绝对路径。大词表易误拦，建议小群试跑。

### 远程审查

- **百度**：只需 Key/Secret，Token 自动换取；可选策略 ID、是否拦「疑似」。
- **自建**：Bearer 鉴权可用 `PALLAS_INBOUND_FILTER_API_KEY`；超时默认 2 秒。

## 排障

| 现象 | 处理 |
| --- | --- |
| 正常话被拦 | 缩小词表/关键词；远程「疑似」可关 `BLOCK_SUSPECTED` |
| 改了词表不生效 | 确认路径；或调用 `reload_message_scrub_caches()` |
| 远程总失败 | 查网络与超时；默认 fail-open 会放行 |

## 关联

- [牛牛复读](../../plugins/repeater/README.md)
- [牛牛做梦](../../plugins/dream/README.md)
- 部署模板：[`deploy/message-scrub/README.md`](../../../deploy/message-scrub/README.md)

## 实现

[`src/features/message_scrub/`](../../../src/features/message_scrub/)
