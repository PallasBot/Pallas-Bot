# sing（牛牛唱歌）

AI 翻唱、续唱、点歌与查歌名；依赖 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 与 `callback` 回传音频。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛唱歌 歌曲名 [key=±N] | 群内 | AI 翻唱 |
| 牛牛继续唱 / 牛牛接着唱 | 群内 | 续唱上一首 |
| 牛牛点歌 歌曲名 | 群内 | 网易云原曲 |
| 牛牛什么歌 / 牛牛哪首歌 | 群内 | 查询当前曲目 |
| 网易云登录 / 网易云登出 | 私聊 | 超管维护 Cookie |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `sing.ncm_login` | superuser |
| `sing.ncm_logout` | superuser |

## 配置

[`config.py`](../../../src/plugins/sing/config.py)：`sing_enable`、AI 地址、`request_endpoint` 等。推荐在 WebUI **插件 → sing** 或 **通用配置 → 服务网关** 修改（落盘 `data/pallas_config/webui.json`，保存后热重载）。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无语音 | 查 AI 服务、`/callback` 可达性；群内发 **牛牛连通** 测唱歌网关 |
| 点歌失败 | 确认网易云登录状态 |

## 实现

[`src/plugins/sing/`](../../../src/plugins/sing/)
