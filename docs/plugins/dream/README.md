# dream（牛牛做梦）

群内发送 **牛牛做梦** 进入做梦状态：牛牛会按随机间隔往群里发「梦话」——可能来自**其它正在做梦的群**的漂流内容、**本 Bot 历史梦记录**、**牛牛画画归档图**，或**复读已学过的句子**。发送 **牛牛醒梦** / **牛牛别做梦** 可立即结束本群做梦。

## 指令与行为

| 触发（纯文本整行匹配） | 说明 |
|------------------------|------|
| `牛牛做梦` | **10 秒群级冷却**+ 每 Bot 每群 **3 秒**（`BotConfig`）；冷却内可能静默；成功后随机持续 **300～900 秒**；随后 worker 在**未醉酒**时按配置（默认 **45～165 秒**）随机间隔推送；**本群醉酒度 > 0 期间**整段改为 **5～20 秒** 间隔。 |
| `牛牛醒梦` / `牛牛别做梦` | 仅在本群已在做梦时生效，结束做梦并清理本群 worker。 |

做梦期间，群友正常聊天会被**异步**写入 `message` 表（与复读学习链路独立），并可能把**最多 2 张**图片（按 CQ 中的 http 链接下载）与**不超过 800 字**的纯文本，**随机投递**到同一 Bot 下**其它正在做梦的群**（若没有其它做梦群则只积累历史，不跨群）。**明文或 raw 含「不可以」** 的消息**不写入梦库、不参与漂流**（避免管理指令进梦）。**历史梦抽样**则对当前 NoneBot 进程内**所有已连接账号**合并查询同一库（多开一号一进程时仍各查各库）。

## 推送优先级（单次 tick）

1. **联机漂流队列（实时）**：他群传来的图或文（图受「本会话已发图」上限约束，见下）。**每个 tick 先**按 **`dream_drift_queue_tick_probability`** 决定是否尝试从队列取一条；取到且发出则本 tick 结束；**未发出任何队列内容时**才进入下面分支。
2. **历史梦（`is_dream`）与已学句（复读 `Context`）**：在上述「本 tick 未发实时漂流」之后，由 **`dream_prefer_learned_echo_probability`**（0～1）掷骰决定**本轮**先尝试哪一支：
   - **先已学句**：从复读已学句随机抽一条（非 CQ 前缀短句），用 **`random_echo_nickname()`** 随机 `@昵称` 当作梦话发出；失败再按下方规则抽历史梦。
   - **先历史梦**（默认、或掷骰未命中时）：从 `message` 里 `keywords` 以 `is_dream` 为前缀、近 **`dream_message_retention_days` 天**、**本进程内各在线 Bot 的 `bot_id` 并集**抽样；优先**非本群**，没有再并集全库；若仍未发出，再同样方式尝试已学句。
   - 两支各自的重试次数分别由 `dream_hist_resample_attempts`、`dream_echo_resample_attempts` 控制。
3. **归档图**：若本轮仍未发出内容，且仍允许发图，则按配置概率尝试拉取 [`pallas_image`](../pallas_image/README.md) 本地归档的成功出图。

本会话内牛牛主动发出的**图片**（漂流图 + 历史图 + 归档图合计）默认最多 **3 张**；**做梦期间首次检测到本群醉酒**后，本场提升至 **5 张**（多解放 2 张）。文本不受该上限计数。

### 做梦 × 醉酒（每场梦仅触发一次）

**醉酒期间**（`drunkenness() > 0`）worker **每一轮**等待均为 **5～20 秒**；**未醉酒**时为配置的随机睡眠（默认 **45～165 秒**）。首场醉酒联动（每场梦仅一次）：在**首次**检测到醉酒的那一轮不发常规梦话，改为尝试与 [`take_name`](../take_name/README.md) 醉酒夺舍一致的操作：牛牛为群管理员时，从 `message` 库随机选一名群友，将牛牛名片改为对方昵称、对方名片改为固定文案之一，并 `update_taken_name`；若成功选中对象，再随机发一条该用户近 **90 天**内、**非 `is_dream`** 的纯文本历史（如有）。本场发图上限 **3→5** 在首场联动成功标记后即生效并保持到醒梦。若牛牛非群管、库中无可用成员或无历史句，仍消耗首场联动（图上限仍会提升），不重复触发夺舍轮。

同一场梦内，**已发过的正文**（规整后小写、空白折叠的文本键）与**已发过的图片**（按图片字节 SHA-256）不会再次投放；历史/归档/已学句抽样会在有限次数内重试换条。漂流队列里与已发重复的内容会被跳过（丢弃该条队列项）。

## 数据与状态

- **进程内**：多群「正在做梦」集合与每群漂流队列在内存中维护；Bot 重启后联机队列清空，**做梦截止时间**以 `BotConfig` 持久化为准（与醉酒等类似，见 `BotConfig.start_dream` / `stop_dream` / `is_dreaming`）。
- **库表**：做梦群聊写入 `message`；`keywords` 形如 `is_dream\x1e{群昵称展示}`，仅用于历史抽样与展示，**不参与**复读 Learner 的关键词逻辑。
- **梦库增长**：不再注册按天定时删除；`is_dream` 记录随做梦采集持续累积。若需按保留天数批量删旧数据，可运维侧调用 [`library_cleanup.py`](../../../src/plugins/dream/library_cleanup.py) 中的 `delete_expired_dream_messages`（Mongo / PostgreSQL 均支持）。

## 配置

本插件使用 NoneBot `get_plugin_config`，配置类在 [`config.py`](../../../src/plugins/dream/config.py)。字段名即环境变量键（通常为大写蛇形，与驱动里 `plugin_config` 写法一致）。常用项：

| 字段 | 默认 | 说明 |
|------|------|------|
| `dream_drift_queue_tick_probability` | `0.8` | 每轮 worker tick 尝试从他群漂流队列取一条实时梦话的概率（0～1）；调低可减少他人实时句占比。 |
| `dream_archive_image_probability` | `0.5` | 走到归档分支时尝试发一张归档画的概率（0～1）。 |
| `dream_echo_resample_attempts` | `22` | 已学句抽样最大重试次数；调高更容易在本 tick 发出一条已学句。 |
| `dream_prefer_learned_echo_probability` | `0.2` | 未发实时漂流后，本 tick 先抽已学句再抽历史梦的概率；`0` 表示永远先历史梦；调高则更常把复读学会的句子当梦话发。 |
| `dream_hist_resample_attempts` | `12` | 历史梦抽样最大重试次数。 |
| `dream_worker_sleep_min_sec` / `dream_worker_sleep_max_sec` | `45` / `165` | **未醉酒**时每轮推送前随机睡眠（秒）；上限须 ≥ 下限。 |
| `dream_message_retention_days` | `90` | 历史梦抽样窗口（天）；手动调用 `delete_expired_dream_messages` 时亦为保留天数。 |
| `dream_history_recent_dedupe_max` | `120` | **每个接收群**近期已发历史去重键数量（跨多场梦仍累计该群）；`0` 关闭。 |
| `dream_history_recency_power` | `2.25` | 历史抽样偏新权重；`0` 为均匀随机。 |

### 入站过滤（与复读共用）

环境变量 **`PALLAS_INBOUND_FILTER_SUBSTRINGS`** 等：本地子串 / 词表与可选远程审查；若命中，本消息**不会**写入做梦库、**不会**参与跨群漂流。规则与复读侧一致，见 [`message_scrub` 说明](../../common/message_scrub/README.md) 与 [`repeater` 文档](../repeater/README.md)。

## 排障

| 现象 | 说明 |
|------|------|
| 发了「牛牛做梦」没反应 | 可能处于 **3 秒冷却**；或发送失败被吞（见日志 `ActionFailed`）。 |
| 只有历史/没有联机 | **仅一台 Bot 只有一个群做梦**时，没有其它接收群，跨群漂流不会出现。 |
| 很少出图 | 历史里带图依赖 CQ 中可下载的 **http(s) url**；归档图依赖 `data/pallas_image/draw_archive/` 是否有文件；本会话图已达上限（默认 3、醉酒联动后 5）后不再发图类内容。 |
| 醒梦无效 | 本群未在做梦时指令会直接返回；需确认是否在**同一群**对**当前在线**的牛牛发送。 |

## 关联

- **牛牛画画** [`pallas_image`](../pallas_image/README.md)：归档图来源与清理策略见该文档。
- **复读**：做梦兜底文案来自已学 `Context`，与做梦写入的 `message` 路径分离。
- **自动夺舍** [`take_name`](../take_name/README.md)：醉酒改名片逻辑与做梦醉酒联动对齐（不含定时里的戳一戳）。
- **管理员「不可以」**：与复读相同触发（回复目标消息后 `@牛牛` + `不可以`，或管理员撤回牛牛消息）时，由本插件 [`ban_handlers.py`](../../../src/plugins/dream/ban_handlers.py) 注册（**priority=4**，早于复读 `priority=5`）从 `message` 表删除 `keywords` 以 `is_dream` 开头且内容匹配的记录；删除范围与本进程历史梦抽样一致，为 **`dream_history_bot_ids` 并集**（多账号同库时一并尝试）。删除逻辑见 [`ban_cleanup.py`](../../../src/plugins/dream/ban_cleanup.py)。**只要实际删到梦库记录**，本插件先发确认句并在 `event.state` 打标，复读侧若也命中封禁则不再重复发同一句。

实现见 [`src/plugins/dream/`](../../../src/plugins/dream/)（入口 [`__init__.py`](../../../src/plugins/dream/__init__.py)，调度 [`runtime.py`](../../../src/plugins/dream/runtime.py)，历史 [`history_bottle.py`](../../../src/plugins/dream/history_bottle.py)，可选批量删旧 [`library_cleanup.py`](../../../src/plugins/dream/library_cleanup.py)，醉酒联动 [`drunk_synergy.py`](../../../src/plugins/dream/drunk_synergy.py)，采集黑名单 [`capture_filter.py`](../../../src/plugins/dream/capture_filter.py)）。
