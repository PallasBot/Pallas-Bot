<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="智能对话">
</p>

<h1 align="center">智能对话 llm_chat</h1>

<p align="center">群里 @牛牛 就能连续聊天，醉酒时也能搭话，并可清空这轮记忆。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。需要部署侧开启智能对话并配置可用的对话 Provider 后，群内才能正常回复。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 群内 `@牛牛 + 消息` | 群内 | 和牛牛多轮聊天，它会记住这轮刚聊过的话。 |
| 醉酒时 `@牛牛` / `牛牛 + 文本` | 群内 | 酒后搭话；须先让牛牛喝酒（例如「牛牛喝酒」）。 |
| `@牛牛 clear` | 群内 | 清空本轮聊天记忆；也可在对话里明确说让它忘记。 |

> 详细用法与「何人可用」以群内帮助图为准。

和「平时群里自然接话」不同：平时接话主要靠复读学习；**明确 @ 牛牛**才走智能对话。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `llm_chat.chat` | 所有人 |
| `llm_chat.clear` | 所有人 |

运维向口令（`换模型`、`卸模型`、`LLM 状态`）默认仅超管可用，普通用户帮助图不展示。实际生效等级以 WebUI「命令权限」为准。

## 配置项

> 可在控制台对应页面中修改。

1. **AI 配置 → 对话**：打开「启用智能对话」，并配置 Provider。
2. 可选：人设提示词、冷却与并发等高级项。
3. 酒后语音等媒体能力需另配 AI 仓相关开关。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 / 帮助里看不到 | 确认已启用智能对话且 Provider 可用；服务不可用时帮助图会暂时隐藏本插件。 |
| 清空不生效 | 确认是在当前群里 `@牛牛 clear`。 |
| 和酒后聊天搞混 | 清醒 `@` 不要求喝酒；酒后须先醉酒，也可用「牛牛 + 文本」。 |
| 和复读搞混 | `@牛牛` 是主动叫它来聊；平时群内接话见 [复读](../repeater/README.md)。 |

## 实现

源码位置：[`packages/llm_chat/`](../../packages/llm_chat/)

关键文件：

- [`__init__.py`](../../packages/llm_chat/__init__.py)：注册元数据、权限和 LLM 工具声明。
- [`chat_message.py`](../../packages/llm_chat/chat_message.py)：处理群内 `@牛牛` 的聊天提交与门控。
- [`drunk_chat.py`](../../packages/llm_chat/drunk_chat.py)：醉酒时 `@` /「牛牛 + 文本」的 drunk 提交路径。
- [`commands.py`](../../packages/llm_chat/commands.py)：处理清空会话命令。

实现要点：

- 清醒 `@牛牛` 与酒后对话共用智能对话总闸与内核 Provider；酒后路径额外依赖 `drink` 醉酒度。
- `clear` 既可由用户手动触发，也可由模型作为工具调用；醒酒时会清本群酒后会话上下文。
- 与 `repeater` 分工：`@牛牛` 负责明确叫牛来聊，平时群内接话仍以语料底盘为主（见 [guide](../../guide/llm-and-repeater.md)）。

## 相关链接

- [牛牛复读](../repeater/README.md)
- [喝酒 drink](../drink/README.md)
- [`@牛牛`、复读接话与 LLM 的关系](../../guide/llm-and-repeater.md)
- [命令权限说明](../../common/cmd_perm/README.md)
