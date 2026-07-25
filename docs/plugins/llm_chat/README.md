<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="智能对话">
</p>

<h1 align="center">智能对话 llm_chat</h1>

<p align="center">群里随时 @牛牛 聊天，也可以清空这轮聊天记录。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。开启 `LLM_CHAT_ENABLED` 并配置 Bot 内核 Provider 即可（媒体能力如唱歌仍可用 Pallas-Bot-AI）。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 群内 `@牛牛 + 消息` | 群内 | 与牛牛多轮聊天。 |
| 醉酒时 `@牛牛` / `牛牛 + 文本` | 群内 | 酒后对话（须先喝酒）。 |
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

1. **AI 配置 → 对话**：打开「启用智能对话」；低配可另开「启用遗留酒后 RWKV」。
2. 通用配置里的智能对话与媒体服务：同上总闸与 AI 地址。
3. 插件页人设提示词等高级项（可选）。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 | 检查 `LLM_CHAT_ENABLED`、Provider；RWKV 路径另查 `CHAT_ENABLE` 与 AI Runtime chat 资源包。 |
| 清空不生效 | 确认是在当前会话里 `@牛牛 clear`。 |
| 和酒后聊天混淆 | 清醒 `@` 不要求喝酒；酒后对话须先醉酒，也可「牛牛 + 文本」。 |

## 实现

源码位置：[`packages/llm_chat/`](../../packages/llm_chat/)

关键文件：

- [`__init__.py`](../../packages/llm_chat/__init__.py)：注册元数据、权限和 LLM 工具声明。
- [`chat_message.py`](../../packages/llm_chat/chat_message.py)：处理群内 `@牛牛` 的聊天提交与门控。
- [`drunk_chat.py`](../../packages/llm_chat/drunk_chat.py)：醉酒时 `@` /「牛牛 + 文本」的 drunk 提交路径。
- [`commands.py`](../../packages/llm_chat/commands.py)：处理清空会话命令。

实现要点：

- 清醒 `@牛牛` 与酒后对话共用 `LLM_CHAT_ENABLED` 与内核 Provider；酒后路径额外依赖 `drink` 醉酒度。
- 会话记忆和工具注入都由统一的 LLM 能力层协调，不是单纯一问一答。
- `clear` 既可由用户手动触发，也可由 LLM 作为工具命令派发；醒酒时会清本群会话上下文。
- 它和 `repeater` 不是对立关系：`@牛牛` 负责明确叫牛来聊，平时群内接话仍以语料底盘为主；两者共用牛格 / 表达参考，成功出口可反哺语料与表达库（见 [guide](../../guide/llm-and-repeater.md)）。
- 酒后可选 `CHAT_TTS_ENABLE`：RWKV 路径随 `/api/chat` 带语音；LLM 路径出字后另调 AI 仓 `/tts`。
- 旧扩展 `pallas-plugin-ai-media` 的 `chat` 已自 4.1.0 移除；若进程里仍加载旧模块，本体会让路。

## 相关链接

- [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)
- [酒后聊天（跳转说明）](../chat/README.md)
- [牛牛复读](../repeater/README.md)
- [`@牛牛`、复读接话与 LLM 的关系](../../guide/llm-and-repeater.md)
