# 智能对话 `llm_chat`

群里 `@牛牛` 可多轮聊天；醉酒时也可搭话，并可清空本轮记忆。需要「明确叫牛来聊」时用本插件；平时群内自然接话仍主要靠 [复读](../repeater/README.md)。

**类型**：本体 core（默认加载）

普通聊天由 Bot 内核直连 Provider，**不必**安装 Pallas-Bot-AI。唱歌 / TTS 等媒体能力才需要 AI Runtime，见 [LLM 对话、媒体与 AI Runtime](../../guide/ai-runtime-choice.md)。

## 安装

默认加载，无需单独安装。须在控制台开启智能对话并配置可用的对话 Provider 后，群内才会回复。

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 群内 `@牛牛 + 消息` | 群内 | 多轮聊天，记住本轮刚聊过的话 |
| 醉酒时 `@牛牛` / `牛牛 + 文本` | 群内 | 酒后搭话；须先让牛牛喝酒（如「牛牛喝酒」） |
| `@牛牛 clear` | 群内 | 清空本轮聊天记忆；也可在对话里明确说让它忘记 |

精确命令与「何人可用」以群内 **牛牛帮助** 为准。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `llm_chat.chat` | 所有人 |
| `llm_chat.clear` | 所有人 |

运维向命令（`换模型`、`卸模型`、`LLM 状态`）默认仅超管可用，普通用户帮助图不展示。实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

1. **AI 配置 → 对话**：打开「启用智能对话」（`LLM_CHAT_ENABLED`），并配置 Provider。
2. 可选：人设提示词、冷却与并发等。
3. 需要文字转语音时安装 `pallas-plugin-ai-media` 并使用「牛牛说」（与普通 `@` 聊天无关）。

保存后写入 `data/pallas_config/webui.json`。步骤见 [AI 扩展](../../guide/ai.md)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无回复 / 帮助里看不到 | 确认已启用智能对话且 Provider 可用；服务不可用时帮助图可能暂时隐藏本插件 |
| 清空不生效 | 确认是在当前群里 `@牛牛 clear` |
| 和酒后 / 复读搞混 | 清醒 `@` 不要求喝酒；酒后须先醉酒；平时接话见 [复读](../repeater/README.md) |

## 源码

[`packages/llm_chat/`](../../../packages/llm_chat/)

- `__init__.py`：元数据、权限与 LLM 工具声明
- `chat_message.py`：群内 `@牛牛` 提交与门控
- `drunk_chat.py`：醉酒时 `@` /「牛牛 + 文本」
- `commands.py`：清空会话

清醒 `@` 与酒后对话共用智能对话总闸与内核 Provider；酒后路径额外依赖 `drink` 醉酒度。与 `repeater` 分工见 [guide](../../guide/llm-and-repeater.md)。

## 相关链接

- [复读 repeater](../repeater/README.md)
- [喝酒 drink](../drink/README.md)
- [`@牛牛` 与复读](../../guide/llm-and-repeater.md)
- [命令权限](../../common/cmd_perm/README.md)
