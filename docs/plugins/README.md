# 插件文档

本目录是各插件的用户 / 维护者说明。每个插件只保留一篇正文：有目录时看 `docs/plugins/<name>/README.md`；否则看扁平 `docs/plugins/<name>.md`。同名扁平文件若存在，只作指向正文的指针。

官方玩法（决斗、MAA、谁是卧底等）默认 slim 不加载，需单独安装。步骤见 [安装插件](/guide/install-plugins)。也可在控制台 **插件商店** 安装，或执行 `uv run pallas ext install pallas-plugin-<name>`。

## 本体 core（默认加载）

| 插件 | 说明 |
| --- | --- |
| [复读 repeater](/plugins/repeater) | 学习群聊、接话、复读 |
| [帮助 help](/plugins/help) | 帮助图、本群开关插件 |
| [欢迎 greeting](/plugins/greeting) | 入群 / 好友欢迎 |
| [喝酒 drink](/plugins/drink) | 喝酒、醒酒 |
| [智能对话 llm_chat](/plugins/llm_chat) | `@牛牛` 连续聊天与酒后搭话 |
| [轮盘 roulette](/plugins/roulette) | 轮盘赌 |
| [夺舍 take_name](/plugins/take_name) | 自动改名片 |
| [拉黑 blacklist](/plugins/blacklist) | 拉黑、屏蔽 |
| [申请 request_handler](/plugins/request_handler) | 好友 / 入群审批 |

## 官方插件（需安装）

| 插件 | pip 包 | 说明 |
| --- | --- | --- |
| [决斗 duel](/plugins/duel) | `pallas-plugin-duel` | 决斗、八角笼 |
| [谁是卧底 who_is_spy](/plugins/who_is_spy) | `pallas-plugin-who-is-spy` | 派对游戏 |
| [做梦 dream](/plugins/dream) | `pallas-plugin-dream` | 做梦、跨群梦话 |
| [画画 draw](/plugins/draw) | `pallas-plugin-draw` | 文生图 |
| [唱歌 sing](/plugins/sing) | `pallas-plugin-ai-media` | 点歌、翻唱（需 AI Runtime） |
| [MAA maa](/plugins/maa) | `pallas-plugin-maa` | 远控排队回图 |
| [协议端 pb_protocol](/plugins/pb_protocol) | `pallas-plugin-protocol` | NapCat / SnowLuma |
| [上号 relogin_bot](/plugins/relogin_bot) | `pallas-plugin-protocol` | 重新登录 |
| [状态 bot_status](/plugins/bot_status) | `pallas-plugin-bot-status` | 在吗、报数与邮件测试 |

酒后对话已并入本体 [llm_chat](/plugins/llm_chat)；旧 [chat](/plugins/chat) 页仅作跳转。

## 运维与控制台

面向控制台配置、进程状态与部署排障，一般不出现在普通用户帮助菜单。

| 插件 | 说明 |
| --- | --- |
| [牛牛核心 pb_core](/plugins/pb_core) | 进程摘要、插件概览与重启 |
| [控制台 pb_webui](/plugins/pb_webui) | 网页控制台与 API |
| [在线统计 pb_stats](/plugins/pb_stats) | 社区主站心跳与上报 |
| [接话行为 persona](/plugins/persona) | 牛格 / 群风格如何影响接话（开发向较多） |

## 通用能力（`docs/common/`）

| 文档 | 说明 |
| --- | --- |
| [cmd_perm](/common/cmd_perm) | 命令权限 |
| [command_limits](/common/command_limits) | 命令冷却 |
| [message_scrub](/common/message_scrub) | 消息审查 |
| [webui](/common/webui) | 配置热重载 |
| [社区共享接话库](/common/corpus) | 本机 + 社区语料 |
| [在线统计](/common/community_stats) | 社区主站心跳与上报 |

## 其它

- 控制台登录口令在 `data/pallas_console/`；遗忘见 [FAQ](/deploy/faq)
- 旧名 / 迁出指针：`community_stats`、`ollama`、`pallas_*` 等扁平 stub
- 正文结构模板：[TEMPLATE.md](./TEMPLATE.md)
- 与文档站同步：[SYNC.md](./SYNC.md)
