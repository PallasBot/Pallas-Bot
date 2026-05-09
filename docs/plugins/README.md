# 插件文档索引

本目录用于存放插件专项说明，优先回答“这个插件要怎么配、怎么用、怎么排障”。

## 已有文档（按插件目录）

- [`pallas_protocol`](./pallas_protocol/README.md)：NapCat/SnowLuma、Docker、`runtime_profile`、`.env` 速查
- [`pallas_webui`](./pallas_webui/README.md)：控制台页面与 API、前端静态资源下载配置
- [`bot_status`](./bot_status/README.md)：状态与通知相关说明
- [`pallas_image`](./pallas_image/README.md)：牛牛画画
- [`relogin_bot`](./relogin_bot/README.md)：牛牛重新上号、创建牛牛（私聊、依赖协议端）
- [`request_handler`](./request_handler/README.md)：好友申请与入群邀请审批、自动同意
- [`help`](./help/README.md)：帮助图与插件开关
- [`repeater`](./repeater/README.md)：牛牛复读、学习对话与表情回应
- [`take_name`](./take_name/README.md)：自动夺舍（群名片）
- [`sing`](./sing/README.md)：牛牛唱歌（依赖 AI 服务与 callback）
- [`callback`](./callback/README.md)：异步任务 HTTP 回调
- [`chat`](./chat/README.md)：酒后聊天（依赖 AI 服务与 callback）
- [`roulette`](./roulette/README.md)：牛牛轮盘
- [`drink`](./drink/README.md)：牛牛喝酒
- [`dream`](./dream/README.md)：牛牛做梦（跨群漂流、历史梦、归档图）
- [`greeting`](./greeting/README.md)：入群/好友欢迎与被踢处理
- [`block`](./block/README.md)：其他牛牛与睡眠期消息拦截

## 使用建议

- 控制台与协议端管理：共用浏览器登录与会话，口令哈希在 `data/pallas_console/`；详见 `pallas_webui` / `pallas_protocol` README；遗忘口令见 [FAQ：部署排障](../FAQ.md#部署排障)
- 完整字段以各插件 `config.py` 为准
- 各子目录 README 文末均附有 **实现见**，链到仓库内 [`src/plugins/`](../../src/plugins/) 下对应目录或入口文件（本页为索引，无单一实现路径）。
