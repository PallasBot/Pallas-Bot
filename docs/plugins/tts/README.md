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

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛说 〈文本〉` | 群内 | 侧车 TTS 合成语音 |

精确口令与「何人可用」以群内 **牛牛帮助** 为准。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `tts.speak` | 所有人 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

控制台插件「牛牛说」页：

- 启用开关、媒体服务地址与端口
- 接口路径（默认 `/v1/tts`）与 Bearer Token（与 AI 侧 `PALLAS_AI_API_TOKEN` 一致）
- 语音通路：`sidecar`（侧车）或 `cloud`（预留，尚未接入）

音色默认值仍在 **AI 配置 → 能力包 → TTS**。

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 没有返回语音 | 确认插件已启用、AI Runtime 在线、`/callback` 可达；`/v1` 鉴权 Token 一致 |
| 提示云端未接入 | 将「语音通路」改为侧车 |

## 源码

扩展仓 `pallas-plugin-ai-media` 中的 `tts` 目录。

仓库：[Plugin-Ai-Media](https://github.com/PallasBot/Plugin-Ai-Media)

## 相关链接

- [唱歌 sing](../sing/README.md)
- [智能对话 llm_chat](../llm_chat/README.md)
- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)
- [命令权限](../../common/cmd_perm/README.md)
