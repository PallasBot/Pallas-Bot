# sing（牛牛唱歌）

> **官方扩展**：`pallas-plugin-ai-media`（`uv sync --extra plugins-ai-media`）

智能翻唱、续唱、点歌与查歌名；需部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛唱歌 歌曲名 [key=±N] | 群内 | AI 翻唱，可调音调 |
| 牛牛继续唱 / 牛牛接着唱 | 群内 | 续唱上一首 |
| 牛牛点歌 歌曲名 | 群内 | 播放网易云原曲 |
| 牛牛什么歌 / 牛牛哪首歌 | 群内 | 查询当前曲目 |
| 网易云登录 / 网易云登出 | 私聊 | 超管维护登录 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `sing.ncm_login` | superuser |
| `sing.ncm_logout` | superuser |

## 配置

WebUI **插件 → 牛牛唱歌** 或 **通用配置 → 外部服务地址**（唱歌服务地址）。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无语音 | 查 AI 服务是否在线；发 **牛牛连通** 测唱歌服务 |
| 点歌失败 | 确认网易云已登录 |

## 实现

[`src/plugins/sing/`](../../../src/plugins/sing/)
