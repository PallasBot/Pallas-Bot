<div align="center">
  <img alt="Pallas-Bot AI" src="https://github.com/user-attachments/assets/fe654813-bf37-4e5f-9c7d-98d867016618" width="427" height="276" />
</div>

# pallas-plugin-ai-media

Pallas-Bot 4.0 官方扩展：**牛牛唱歌**（`sing`）。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**，并部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。

```bash
# 推荐：控制台 → 插件商店 → 一键安装
uv run pallas ext install pallas-plugin-ai-media
# 或：uv pip install pallas-plugin-ai-media
```

## 功能说明

### 牛牛唱歌（sing）

AI 翻唱、续唱、点歌与查歌名；依赖 AI 仓与本体 `callback` 回传音频。

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛唱歌 歌曲名 [key=±N] | 群内 | AI 翻唱 |
| 牛牛继续唱 / 牛牛接着唱 | 群内 | 续唱上一首 |
| 牛牛点歌 歌曲名 | 群内 | 网易云原曲 |
| 牛牛什么歌 / 牛牛哪首歌 | 群内 | 查询当前曲目 |
| 网易云登录 / 网易云登出 | 私聊 | 超管维护 Cookie |

| 命令 ID | 默认等级 |
| --- | --- |
| `sing.ncm_login` | 仅超管 |
| `sing.ncm_logout` | 仅超管 |

配置：[`src/pallas_plugin_sing/config.py`](src/pallas_plugin_sing/config.py)

> 酒后对话已迁入本体 `llm_chat`（可选 `CHAT_TTS_ENABLE` 走 AI 仓 TTS）。

### 排障

| 现象 | 处理 |
| --- | --- |
| 唱歌无语音 | 查 AI 服务、`/callback` 可达；**牛牛连通** 测唱歌网关 |

## 文档

| 说明 | 链接 |
| --- | --- |
| 唱歌 | [文档站 · sing](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/sing) |
| 智能对话 / 酒后 | [文档站 · llm_chat](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/llm_chat) |

## 源码

- [`src/pallas_plugin_sing/`](src/pallas_plugin_sing/)
