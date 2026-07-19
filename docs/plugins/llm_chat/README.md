<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="随时闲聊">
</p>

<h1 align="center">随时闲聊 llm_chat</h1>

<p align="center">群里随时 @牛牛 聊天，也可以清空这轮聊天记录。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。使用前需要部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 并开启 `LLM_CHAT_ENABLED`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 群内 `@牛牛 + 消息` | 群内 | 与牛牛多轮聊天。 |
| `@牛牛 clear` | 群内 | 清空本群当前会话记忆。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `llm_chat.chat` | 所有人 |
| `llm_chat.clear` | 所有人 |

运维向的 `换模型`、`卸模型`、`LLM 状态` 默认只给超管使用，不面向普通帮助菜单展示。

## 配置项

> 可在控制台对应插件页中修改。

1. 通用配置里的智能对话和 AI 服务：开启总开关并填写服务地址。
2. 插件页里的随时闲聊配置：可选调整人设提示词等高级项。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 检查 `LLM_CHAT_ENABLED`、AI 服务和 `牛牛连通` 结果。 |
| 清空不生效 | 确认是在当前会话里 `@牛牛 clear`。 |
| 和酒后聊天混淆 | 随时闲聊不要求喝酒；酒后聊天必须先醉酒。 |

## 实现

源码位置：[`packages/llm_chat/`](../../packages/llm_chat/)

关键文件：

- [`__init__.py`](../../packages/llm_chat/__init__.py)：注册元数据、权限和 LLM 工具声明。
- [`chat_message.py`](../../packages/llm_chat/chat_message.py)：处理群内 `@牛牛` 的聊天提交与门控。
- [`commands.py`](../../packages/llm_chat/commands.py)：处理清空会话命令。

实现要点：

- 这是常驻的 `@牛牛` 对话能力，不依赖醉酒状态。
- 会话记忆和工具注入都由统一的 LLM 能力层协调，不是单纯一问一答。
- `clear` 既可由用户手动触发，也可由 LLM 作为工具命令派发。
- 它和 `repeater` 不是对立关系：`@牛牛` 负责明确叫牛来聊，平时群内接话仍以语料底盘为主。
- direct chat 与 repeater 共用 conversation kernel 的 scene/decision trace，但入口与产品语义保持独立。
- 若开启 `LLM_REPEATER_MODE`，接话路径也可能让 LLM 做补位或轻润色，但不取代语料学习本身。

## 相关链接

- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)
- [酒后聊天](../chat/README.md)
- [牛牛复读](../repeater/README.md)
- [`@牛牛`、复读接话与 LLM 的关系](../../guide/llm-and-repeater.md)
