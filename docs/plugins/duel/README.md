# duel（牛牛决斗）

泰拉风味多幕群决斗：从 `event_packs` 抽剧目、干员辨认/关键词 QTE、双牛八角笼与胜负惩罚（默认 **5** 幕，可配置）。

## 指令

| 触发 | 命令 ID | 默认谁可发 |
|------|---------|------------|
| `牛牛决斗` @一名对手 | `duel.duel` | 所有人 |
| `牛牛决斗` @牛A @牛B（双牛） | `duel.duel` | 所有人 |
| `八角笼牛` | `duel.cage` | 所有人 |
| `决斗事件重载` | `duel.reload_events` | 群管/群主 |

群聊入口的 **「何人可用」** 以 WebUI「通用配置 → 命令权限」与 [cmd_perm](../../common/cmd_perm/README.md) 为准；上表为代码默认等级。

重载内容：`event_packs/default/` 四池 JSON、`operators_6star.json` 缓存，并清空未决 QTE。
**不会**重读 `.env` 插件配置；配置热重载见 WebUI 插件配置页（`reload_duel_plugin_config`）。

## 配置

字段定义见 [`src/plugins/duel/config.py`](../../../src/plugins/duel/config.py)。WebUI「插件配置 → duel」可读写，保存后调用 `reload_duel_plugin_config()`。

主要分组：

- **胜负惩罚**：时长、败/胜者名片、双牛/人类局消息替换与撤回文案
- **流程**：总幕数（默认 5）、多 Bot 抢答冷却、幕间随机停顿、紧凑发群
- **事件与 QTE**：公共幕权重、QTE 事件权重倍率、兵刃幕额外 QTE 概率
- **泰拉干员资源**：缺表自动拉取、本地头像目录、按需/启动批量下载头像
- **牛自动 QTE**：咏名/拆招成功率与失败时嘴瓢、沉默概率

## 胜负惩罚（非独立命令）

决斗正常结束后由 `duel_penalty` 应用（无 `command_permission` 条目）：

| 对局 | 行为 |
|------|------|
| 双牛 | 败者/胜者改群名片；败者后续发言替换为配置文案 |
| 人类，且**处理决斗的牛**为群管 | 败者消息撤回 + 代发噪音文案 |
| 人类，牛非群管 | 仅改败者名片（若 API 允许） |
| 牛败 | 胜方牛后续发言替换为「伤心」文案 |

状态写在 `GroupConfig` 内存键 `duel_penalties`，期满自动恢复名片。

## 事件包与干员表

- 撰写约定：[event_packs/README.md](../../../src/plugins/duel/event_packs/README.md)
- 六星表：`resource/arknights/operators_6star.json`
- 乱入头像：`resource/arknights/avatars/{char_id}.png`（随仓库分发，全量约 **8MB** / 140 张）

### 同步脚本（推荐部署后执行一次）

```bash
# 干员表 + 补全缺失头像
uv run python scripts/fetch_arknights_duel_data.py

# 仅更新 JSON
uv run python scripts/fetch_arknights_duel_data.py --no-avatars

# 仅补头像（已有 JSON 时）
uv run python scripts/fetch_arknights_duel_data.py --avatars-only
```

逻辑与运行时安装器共用 [`src/common/arknights/duel_sync.py`](../../../src/common/arknights/duel_sync.py)。

### 启动时自动安装（类似语音 `ensure_voices`）

插件 `on_startup` 通过 `schedule_arknights_duel_resource_sync` **在后台任务中**拉取，**不阻塞** Bot 连接 QQ；表已存在且未开「启动批量头像」时不会发起同步。

| 配置键 | 默认 | 行为 |
|--------|------|------|
| `duel_auto_sync_operators` | `true` | 缺表或 `count=0` 时后台拉取 character/skill 表并写入 JSON |
| `duel_avatar_download_on_use` | `true` | 本地缺 PNG 时按需拉到 `resource/avatars`（发群用 **bytes**，同 greeting） |
| `duel_avatar_download_on_startup` | `false` | 启动后后台批量补全缺失头像（仓库已带头像时通常不必开） |

乱入 `show_avatar` 仅读本地 PNG 并以 **bytes** 发图（与 greeting 一致，不用 `file://`/远程 URL）；合并失败时拆成「文本 + 头像」两条。缺表时乱入 QTE 会降级，直至后台 JSON 写完。

### 资源更新

头像与六星表已随仓库分发。若游戏侧新增六星或头像变更，维护者本地执行：

```bash
uv run python scripts/fetch_arknights_duel_data.py
```

后提交 `operators_6star.json` 与 `avatars/` 即可。未拉全库时仍可由启动后台同步或 `duel_avatar_download_on_use` 按需补单张。

## 与其它插件

- **block**：双牛决斗配对期间，配对牛互可见消息，其它牛仍被拦截（见 `duel_session.is_duel_paired_bot_traffic`）
- **repeater**：决斗进行中的剧目台词默认不入学习（见 `duel_send`）

## 排障

| 现象 | 说明 |
|------|------|
| 提示剧目表读不出 | 检查 `event_packs/default/*.json` 是否为合法 JSON 数组 |
| 重载无反应 | 确认发送者为群管/群主，或 WebUI 已将 `duel.reload_events` 放开给所有人 |
| 乱入无干员 | 运行 `uv run python scripts/fetch_arknights_duel_data.py`，或确认 `duel_auto_sync_operators=true` 且机器可访问 GitHub |
| 泰拉节庆/乱入无头像 | 确认 `resource/arknights/avatars/` 齐全或开 `duel_avatar_download_on_use`；日志 `missing local avatar` 表示本地无图 |
| 乱入 `send_msg timeout` | 头像已随仓库分发时应走本地 file；仍超时看 NapCat/合并消息体积，代码会尝试拆条发图 |
| 八角笼无法开演 | 本群在线牛牛账号不足 2（`duel_bots` 配置集合） |

## 实现索引

| 模块 | 职责 |
|------|------|
| [`__init__.py`](../../../src/plugins/duel/__init__.py) | 入口、matcher、metadata |
| [`duel_round_engine.py`](../../../src/plugins/duel/duel_round_engine.py) | 多幕流程、效果、重载池 |
| [`duel_qte.py`](../../../src/plugins/duel/duel_qte.py) | QTE、牛自动应答 |
| [`duel_penalty.py`](../../../src/plugins/duel/duel_penalty.py) | 胜负惩罚 |
| [`duel_send.py`](../../../src/plugins/duel/duel_send.py) | 幕缓冲发送、发群失败回退 |
| [`arknights_ops.py`](../../../src/plugins/duel/arknights_ops.py) | 六星表读取、乱入头像路径解析 |

**刷屏**：默认 `duel_compact_round=true`（合并幕内消息、乱入头像与唤名同条、QTE 与上文同条）；双方 HP/DP 附在**本幕 flush 末尾**，括号内为本幕变动（场层加伤已计入 HP）。仍觉冗长可改 `event_packs` 或调低 QTE 权重。
