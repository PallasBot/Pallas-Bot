<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="酒后聊天">
</p>

<h1 align="center">酒后聊天</h1>

<p align="center">能力已并入本体 <a href="/plugins/llm_chat">智能对话 llm_chat</a>；本页保留作跳转说明。</p>

## 现状

自 `pallas-plugin-ai-media` **4.1.0** 起，扩展包不再包含 `chat` 子插件。醉酒时 `@牛牛` /「牛牛 + 文本」由本体 `llm_chat.drunk_chat` 处理。

可选语音：AI 配置 → 对话 → **酒后对话附带语音**（`CHAT_TTS_ENABLE`），走 AI Runtime TTS（与旧扩展同源）。

遗留 RWKV：仍可用 `CHAT_ENABLE` 走 AI 仓 `/api/chat`（与 `LLM_CHAT_ENABLED` 独立；两者都开时优先 LLM）。

若站点仍安装 **4.0.x** 且加载了旧 `pallas_plugin_chat`，本体会继续让路给扩展；升级到 4.1.0+ 后即由本体承接。

## 相关链接

- [智能对话 llm_chat](/plugins/llm_chat)
- [牛牛唱歌](/plugins/sing)
