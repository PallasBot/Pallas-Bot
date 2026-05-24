# chat（酒后聊天）

牛牛**醉酒**时可用 ChatRWKV 对话；需部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。

## 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| @牛牛 | 群内 | 醉酒时 AI 回复 |
| 牛牛 + 文本 | 群内 | 同上 |

## 命令权限

无独立命令 ID（依赖醉酒状态，非 cmd_perm 口令）。

## 配置

[`config.py`](../../../src/plugins/chat/config.py)：`chat_enable`、`ai_server_host`、`ai_server_port` 等。推荐在 WebUI **插件 → chat** 修改（落盘 `data/pallas_config/webui.json`）。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 确认已喝酒、AI 服务可达、`chat_enable=true` |
| 冷却 | 群级冷却内可能静默 |

## 实现

[`src/plugins/chat/`](../../../src/plugins/chat/)
