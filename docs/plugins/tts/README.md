# 牛牛说 `tts`

群内把文字念成语音。需要 TTS 时安装；依赖 **Pallas-Bot-AI（AI Runtime）**，与普通 `@牛牛` 聊天无关。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-ai-media
```

另需部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)，并在控制台配置媒体服务与 TTS 音色。见 [LLM 对话、媒体与 AI Runtime](../../guide/ai-runtime-choice.md)。

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛说 〈文本〉` | 群内 | 侧车 TTS 合成语音（**「牛牛说」后须有空格**） |
| `@牛牛` 里明确要求念 / 读出来 | 群内 | 可走 LLM 工具 `tts.speak`（须开启工具与 soft recall） |

精确命令与「何人可用」以群内 **牛牛帮助** 为准。

不要用「牛牛说啥呢」这种粘连句当口令——中间没空格时不会当「牛牛说」处理，以免挡住正常闲聊。

## 酒后自动跟语音（可选）

与手动「牛牛说」分开：醉酒搭话出字后，可再 enqueue 一条 TTS（先文字、后语音）。

在控制台 **智能对话**（或 `CHAT_TTS_*` / `DRUNK_TTS_*`）配置：

| 项 | 默认 | 说明 |
| --- | --- | --- |
| `CHAT_TTS_ENABLE` | 关 | 总开关 |
| `DRUNK_TTS_MIN_DRUNKENNESS` | `1` | 该牛本群醉酒度下限（见 [drink](../drink/README.md)） |
| `DRUNK_TTS_MIN_CHARS` | `6` | 本次酒后回文最短字数 |

还须：本插件启用、`TTS_ENABLE=true`、媒体服务与音色可用。未达标时只出字、不报错。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `tts.speak` | 所有人 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

推荐在控制台 **AI 配置 → 媒体**：

| 面板 | 配置什么 |
| --- | --- |
| **媒体服务 · 连接** | 服务地址与 **Bearer Token**（同步 `AI_SERVER_*` / `TTS_API_TOKEN`） |
| **TTS** | 侧车参考音色默认；**中翻日**开关与百度/有道密钥（单独「保存翻译配置」）；嵌入插件配置（启停、通路、超时、字数） |

自 `pallas-plugin-ai-media` **4.3.0** 起，插件页不再展示服务地址 / Bearer / endpoint（由媒体连接统一管理）。接口默认仍为 `/v1/tts`。

翻译落盘在 AI Runtime 的 `data/media_models.json`（`translator` 段）；控制台未保存过时回退 AI 侧 `.env` 的 `TRANSLATOR_*`。开启且译成功后按日语合成；失败则保留原文与「合成语种」。

保存后写入 `data/pallas_config/webui.json`（Bot）与 AI 侧 `media_models.json`（音色/翻译）。

## 排障

| 现象 | 处理 |
| --- | --- |
| 「牛牛说」无语音 | 确认插件已启用、AI Runtime 在线、`/callback` 可达；媒体连接 Bearer 与 AI 侧 `PALLAS_AI_API_TOKEN` 一致；口令中间是否有空格 |
| 「牛牛说啥呢」却出声 | 已改为前缀后须空白；升级 ai-media 后应不再误触发 |
| `@` 让念出来只回文字 | 确认 `LLM_TOOLS_ENABLED` / soft recall；hints 含「念出来」「把你的话」等；被回复原文应作为工具 `text` |
| 语音听感截断 / 怪 | 查控制台 TTS「中翻日」与合成语种：译失败不应再强行按日语合成；音色默认与 prompt 语言是否匹配 |
| 提示云端未接入 | 将「语音通路」改为侧车 |

## 源码

扩展仓 `pallas-plugin-ai-media` 中的 `tts` 目录。

仓库：[Plugin-Ai-Media](https://github.com/PallasBot/Plugin-Ai-Media)

## 相关链接

- [唱歌 sing](../sing/README.md)
- [智能对话 llm_chat](../llm_chat/README.md)
- [喝酒 drink](../drink/README.md)
- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)
- [命令权限](../../common/cmd_perm/README.md)
