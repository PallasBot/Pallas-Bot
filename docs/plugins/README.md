# 插件文档索引

各插件的「怎么配、怎么用、怎么排障」见子目录 `README.md`（结构见 [TEMPLATE.md](./TEMPLATE.md)）。**群内怎么说、谁能用**以 **牛牛帮助** 为准；本文档面向部署者与群管。

**配置**：有 `config.py` 的插件可在 WebUI **插件** 或 **通用配置** 中修改，落盘 `data/pallas_config/webui.json`。

## 本体 core（默认加载）

| 文档 | 说明 |
| --- | --- |
| [repeater](./repeater/README.md) | 学习群聊、接话、复读 |
| [help](./help/README.md) | 帮助图、本群开关插件 |
| [greeting](./greeting/README.md) | 入群/好友欢迎 |
| [drink](./drink/README.md) | 喝酒 / 醒酒 |
| [roulette](./roulette/README.md) | 轮盘 |
| [take_name](./take_name/README.md) | 自动改名片（夺舍） |
| [blacklist](./blacklist/README.md) | 拉黑 / 屏蔽 |
| [request_handler](./request_handler/README.md) | 好友/入群申请 |
| [pallas_webui](./pallas_webui/README.md) | 网页控制台 |

## 官方扩展（bundled，默认 slim 不加载）

安装：`uv sync --extra plugins-<名>` 或 WebUI **官方扩展**。源码仍在 `src/plugins/`。

| 文档 | 扩展包 | 说明 |
| --- | --- | --- |
| [duel](./duel/README.md) | `pallas-plugin-duel` | 决斗、八角笼 |
| [who_is_spy](./who_is_spy/README.md) | `pallas-plugin-who-is-spy` | 谁是卧底 |
| [dream](./dream/README.md) | `pallas-plugin-dream` | 做梦、跨群梦话 |
| [draw](./draw/README.md) | `pallas-plugin-draw` | 画画 |
| [sing](./sing/README.md) | `pallas-plugin-ai-media` | 唱歌、点歌 |
| [chat](./chat/README.md) | `pallas-plugin-ai-media` | 酒后智能对话 |
| [llm_chat](./llm_chat/README.md) | `pallas-plugin-llm-chat` | 随时闲聊 |
| [maa](./maa/README.md) | `pallas-plugin-maa` | MAA 远控 |
| [pallas_protocol](./pallas_protocol/README.md) | `pallas-plugin-protocol` | NapCat/SnowLuma |
| [relogin_bot](./relogin_bot/README.md) | `pallas-plugin-protocol` | 重新上号 |
| [bot_status](./bot_status/README.md) | `pallas-plugin-bot-status` | 在吗、报数、邮件 |
| [community_stats](./community_stats/README.md) | `pallas-plugin-community-stats` | 社区统计上报 |

## 已内核化（无独立插件目录）

| 文档 | 说明 |
| --- | --- |
| [connectivity](./connectivity/README.md) | 牛牛连通（`features/service_gateways`） |
| [block](./block/README.md) | 其它牛牛消息拦截（`platform/multi_bot/bot_filter`） |
| [callback](./callback/README.md) | 异步任务结果回传（`platform/ai_callback`） |
| [ingress_gate](./ingress_gate/README.md) | 群消息预处理（`platform/ingress/gate`） |

## 通用能力（`docs/common/`）

| 文档 | 说明 |
| --- | --- |
| [cmd_perm](../common/cmd_perm/README.md) | 命令权限 |
| [command_limits](../common/command_limits/README.md) | 命令冷却 |
| [message_scrub](../common/message_scrub/README.md) | 消息审查 |
| [webui](../common/webui/README.md) | 配置热重载 |
| [社区共享接话库](../common/corpus/README.md) | 本机 + 社区语料 |
| [在线统计](../common/community_stats.md) | 社区主站上报 |

## 其它

- [persona](./persona/README.md)：接话行为（群风格等，开发向较多）
- 控制台登录口令在 `data/pallas_console/`；遗忘见 [FAQ](../FAQ.md)
