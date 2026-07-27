# 酒后聊天（已并入 llm_chat）

能力已并入本体 [智能对话 llm_chat](../llm_chat/README.md)。本页仅作跳转。

自 `pallas-plugin-ai-media` **4.1.0** 起，扩展包不再包含 `chat` 子插件。醉酒时 `@牛牛` / 「牛牛 + 文本」由本体 `llm_chat.drunk_chat` 处理（纯文字）。需要念出来时用扩展包「牛牛说」。

遗留 RWKV：仍可用 `CHAT_ENABLE` 走 AI 仓 `/api/chat`（与 `LLM_CHAT_ENABLED` 独立；两者都开时优先 LLM）。见 [LLM 对话、媒体与 AI Runtime](../../guide/ai-runtime-choice.md)。

若站点仍安装 **4.0.x** 且加载了旧 `pallas_plugin_chat`，本体会继续让路给扩展；升级到 4.1.0+ 后由本体承接。

## 相关链接

- [智能对话 llm_chat](../llm_chat/README.md)
- [唱歌 sing](../sing/README.md)
- [牛牛说 tts](../tts/README.md)
