# llm_chat（随时闲聊）

> **官方扩展**：`pallas-plugin-llm-chat`（`uv sync --extra plugins-llm-chat`）

群内 @牛牛 多轮智能对话；需部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 并在控制台开启智能对话。

模型与人设由部署者在服务端配置，**不提供**群内更换模型或卸载模型的口令。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| @牛牛 + 消息 | 群内 | 多轮对话 |
| @牛牛 clear | 群内 | 清空本会话记忆 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `llm_chat.chat` | everyone |
| `llm_chat.clear` | everyone |

## 配置

1. **通用配置 → 智能对话与 AI 服务**：开启总开关，填写服务地址。
2. **插件 → 随时闲聊**：可选自定义人设提示词文件（维护者向，勿暴露给群用户修改入口）。

酒后 `chat` 插件与随时闲聊共用同一总开关。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 确认总开关已开、AI 服务在跑；发 `牛牛连通` 测延迟 |
| 与酒后聊天混淆 | 随时 @ 即可；酒后须先「牛牛喝酒」 |

## 实现

[`src/plugins/llm_chat/`](../../../src/plugins/llm_chat/)
