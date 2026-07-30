# LLM 对话、媒体与 AI Runtime

Pallas-Bot 的日常 LLM 对话和媒体任务使用不同的运行路径。先按要启用的能力选择组件，再配置对应服务。

## 选择组件

| 需要的能力 | 要配置什么 | 是否需要 Pallas-Bot-AI |
| --- | --- | --- |
| `@牛牛` LLM 对话、接话、记忆、工具调用 | Bot 控制台中的 Provider、模型与对话开关 | 不需要 |
| 使用云端或本机 Ollama 模型聊天 | Provider 的 Base URL、密钥与模型 | 不需要 |
| 唱歌、TTS 等媒体任务 | AI Runtime、媒体能力包和对应插件 | 需要 |
| 遗留 RWKV 酒后对话 | AI Runtime 与旧聊天资源包 | 需要 |

普通聊天由 Bot 进程直接请求 Provider。媒体服务离线不会阻止 `@牛牛` 聊天；反过来，Provider 可用也不能代替媒体运行环境。

## 配置普通聊天

1. 登录网页控制台，进入 **AI 配置** 的 Provider 接入区。
2. 填写服务地址、密钥和模型，完成测通并保存。
3. 在 **AI 配置 → 接话** 打开 `LLM_CHAT_ENABLED`。
4. 在群里 `@牛牛` 发送一句消息，或使用 `牛牛连通` 验证连接。

保存后的配置由控制台写入 `data/pallas_config/webui.json`。这个文件是运行结果，日常不需要手动修改。

Provider 的字段说明和接话设置见 [AI 扩展](ai.md) 与 [@牛牛与复读](llm-and-repeater.md)。

## 按需增加媒体能力

唱歌、TTS 或遗留 RWKV 需要额外部署 Pallas-Bot-AI。部署完成后，在控制台的媒体服务区域配置连接，再安装相应能力包和插件。

媒体安装步骤见 [AI Runtime 安装](/maintainer/install/ai-runtime)。Docker 部署请参阅 [Docker 部署](/deploy/docker)。

## 排查入口

- `@牛牛` 没有回复：确认 `LLM_CHAT_ENABLED` 和 Provider 测通状态。
- 媒体任务没有结果：确认 AI Runtime、媒体能力包和 callback。
- 记忆检索不符合预期：确认存储已初始化；未配置可用 embedding 时，系统会使用关键词检索。

完整排障顺序见 [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)。
