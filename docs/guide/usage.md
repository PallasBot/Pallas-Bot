# 命令与功能

牛牛在群里用命令（或 @ 牛牛）触发功能，完整列表与「何人可用」以 **牛牛帮助** 帮助图为准。本页只作索引，按「开箱即有 / 需安装官方插件 / 需额外能力」三组速查。

::: details 说明：权限三个词
| 词 | 意思 |
| --- | --- |
| 超管 | `pallas.toml` 里 `superusers` |
| 号主 | 该牛 `admins` 列表里的 QQ；配置见 [号主](bot-owner.md) |
| 群管 | QQ 群管理员 |
:::

## 开箱即有

| 命令 | 作用 |
| --- | --- |
| `牛牛帮助` | 功能帮助图；群管可关单群插件 |
| `牛牛` | 打招呼（多牛同群可能齐回） |
| `牛牛喝酒` / `醒一醒` | 喝酒玩法 |
| `牛牛轮盘` | 轮盘；`牛牛救一下` / `牛牛补一枪` |
| （自然接话） | 学群友说话后复读接话 |

## 需安装官方插件

| 命令 | 插件包 |
| --- | --- |
| 决斗、八角笼 | `pallas-plugin-duel` |
| 谁是卧底 | `pallas-plugin-who-is-spy` |
| `牛牛做梦` | `pallas-plugin-dream` |
| MAA 远控 | `pallas-plugin-maa` |

安装步骤见 [安装插件](install-plugins.md)

## 需额外能力

| 命令 | 依赖 |
| --- | --- |
| `牛牛唱歌` / `牛牛点歌` / `牛牛说` | [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)（AI Runtime）+ `pallas-plugin-ai-media` |
| `牛牛画画` | 画画插件网关 + `pallas-plugin-draw`（默认不经 AI Runtime） |
| @ 牛 LLM 对话 | 控制台 **AI 配置** 打开 `LLM_CHAT_ENABLED`，并配置 Bot Provider；见 [AI 扩展](ai.md) |

连通性测试：群里发 `牛牛连通`。

## 成功信号

- 群里发 `牛牛帮助` 能收到帮助图。
- 已装插件的命令出现在帮助图中；AI 相关命令在 Provider / Runtime 配好后可用。

## 控制台入口

| 任务 | 地址 / 侧栏 |
| --- | --- |
| 改配置 | `http://<主机>:8088/pallas/` |
| 扫码上 QQ | `/pallas/protocol` |
| 关插件 | 控制台 **插件** |
| 配 Provider / 媒体 | **AI 配置** |

面板说明见 [网页控制台](web-console.md)

## 接下来做什么

- [网页控制台](web-console.md)
- [@牛牛与复读](llm-and-repeater.md)
- [LLM 对话、媒体与 AI Runtime](ai-runtime-choice.md)
