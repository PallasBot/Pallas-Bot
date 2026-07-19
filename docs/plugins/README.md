# 插件文档索引

::: info 官方插件
决斗、MAA、谁是卧底等玩法在 **官方插件 pip 包** 中，默认 slim 不加载。安装见 [安装插件](/guide/install-plugins) 或控制台 **插件商店**。
:::

## 本体 core（默认加载）

<div class="plugin-doc-grid">

<NCard title="复读 repeater" route="/plugins/repeater">学习群聊、接话、复读</NCard>
<NCard title="帮助 help" route="/plugins/help">帮助图、本群开关插件</NCard>
<NCard title="欢迎 greeting" route="/plugins/greeting">入群 / 好友欢迎</NCard>
<NCard title="喝酒 drink" route="/plugins/drink">喝酒、醒酒</NCard>
<NCard title="轮盘 roulette" route="/plugins/roulette">轮盘赌</NCard>
<NCard title="夺舍 take_name" route="/plugins/take_name">自动改名片</NCard>
<NCard title="拉黑 blacklist" route="/plugins/blacklist">拉黑、屏蔽</NCard>
<NCard title="申请 request_handler" route="/plugins/request_handler">好友 / 入群审批</NCard>

</div>

## 官方插件（需安装）

安装：可在控制台插件商店安装，也可使用 `uv run pallas ext install pallas-plugin-<name>`。源码仍在对应扩展仓中。

<div class="plugin-doc-grid">

<NCard title="决斗 duel" route="/plugins/duel">决斗、八角笼 · pallas-plugin-duel</NCard>
<NCard title="谁是卧底" route="/plugins/who_is_spy">派对游戏 · pallas-plugin-who-is-spy</NCard>
<NCard title="做梦 dream" route="/plugins/dream">做梦、跨群梦话 · pallas-plugin-dream</NCard>
<NCard title="画画 draw" route="/plugins/draw">文生图 · pallas-plugin-draw</NCard>
<NCard title="唱歌 sing" route="/plugins/sing">点歌 · pallas-plugin-ai-media</NCard>
<NCard title="聊天 chat" route="/plugins/chat">酒后智能对话 · pallas-plugin-ai-media</NCard>
<NCard title="MAA maa" route="/plugins/maa">远控排队回图 · pallas-plugin-maa</NCard>
<NCard title="协议端" route="/plugins/pb_protocol">NapCat / SnowLuma · pallas-plugin-protocol</NCard>
<NCard title="上号 relogin_bot" route="/plugins/relogin_bot">重新登录 · pallas-plugin-protocol</NCard>

</div>

## 运维与控制台

这些文档通常不会出现在普通用户帮助菜单里，主要用于控制台配置、进程状态和部署排障。

<div class="plugin-doc-grid">

<NCard title="闲聊 llm_chat" route="/plugins/llm_chat">随时 @ 智能闲聊与 AI 开关</NCard>
<NCard title="牛牛核心 pb_core" route="/plugins/pb_core">进程摘要、插件概览与重启</NCard>
<NCard title="控制台 pb_webui" route="/plugins/pb_webui">网页控制台与 API</NCard>
<NCard title="在线统计 pb_stats" route="/plugins/pb_stats">社区主站心跳与上报</NCard>
<NCard title="状态 bot_status" route="/plugins/bot_status">在吗、报数与邮件测试</NCard>

</div>

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

- [persona](/plugins/persona)：接话行为（群风格等，开发向较多）
- 控制台登录口令在 `data/pallas_console/`；遗忘见 [FAQ](/deploy/faq)
- 文档结构模板：[TEMPLATE.md](https://github.com/PallasBot/Pallas-Bot/blob/main/docs/plugins/TEMPLATE.md)
