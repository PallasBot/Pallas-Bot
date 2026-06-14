# who_is_spy（牛牛卧底）

群内谁是卧底：开房、自由讨论、房主发起投票、私聊匿名投票，直至一方阵营获胜。

## 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛卧底 | 群内 | 开房 |
| 牛牛加入 / 牛牛退出 | 群内 | 筹备阶段进出 |
| 牛牛发身份 [潜藏人数] [白板] [暗牌\|明牌] | 群内 | 房主开局并下发词语 |
| @牛牛 + 描述 | 群内 | 讨论阶段记为述词 |
| 牛牛投票 | 群内 | 房主提前开始投票（先发复盘） |
| 私聊回复数字序号或 0 | 私聊 | 投票（0=弃权） |
| 牛牛局势 / 牛牛结束 | 群内 | 察看局势、结束房间 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `who_is_spy.open` | everyone |
| `who_is_spy.join` | everyone |
| `who_is_spy.start` | everyone（含牛牛投票） |
| `who_is_spy.status` | everyone |
| `who_is_spy.end` | everyone |

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `spy_min_players` | 4 | 最少开局人数 |
| `spy_max_players` | 12 | 房间上限 |
| `spy_default_undercovers` | 1 | 默认卧底数 |
| `spy_default_blanks` | 0 | 默认白板数（无词，不计入胜负比较） |
| `spy_show_role_default` | false | 私聊是否附带身份（false=暗牌，只发词） |
| `spy_word_avoid_recent` | 10 | 同群最近 N 局词对不重复，0 关闭 |
| `spy_auto_vote_when_all_spoken` | true | 全员 @牛牛 述词后自动投票 |
| `spy_speak_max_len` | 120 | 复盘单条述词最大字数 |
| `spy_room_cleanup_sec` | 600 | 局结束后空房清理秒数 |
| `spy_email_fallback` | true | 私聊失败时改发玩家 QQ 邮箱 |

字段以 [`config.py`](../../../src/plugins/who_is_spy/config.py) 为准；WebUI **插件 → 牛牛卧底** 修改。

**私聊与邮箱**：发词/投票说明优先好友私聊；失败时尝试带 `group_id` 的临时会话；仍失败且 `spy_email_fallback=true` 时，复用 **bot_status** 的 SMTP 向 `{QQ号}@qq.com` 发信。

词库内置 `resource/who_is_spy/undercover_words.json`；运行期使用 `data/who_is_spy/undercover_words.json`（首次启动从 resource 复制，之后启动自动合并 resource 新增词对）。编辑 JSON 后重启 Bot 生效。

## 排障

| 现象 | 处理 |
| --- | --- |
| 收不到词语/投票私聊 | 加牛牛好友；或查 QQ 邮箱；确认 bot_status SMTP 已配置 |
| 私聊「你的词：」后无字 | 非白板玩法，属投递失败；加好友、查邮箱或看开局提示里的未达名单 |
| 本群已有房间 | 分片下同群互斥；「牛牛结束」或等局后自动清理 |
| @牛牛 述词无回复 | 分片多牛须 @ **本局主持牛**（发「词已私聊」的那只）；述词优先于 Ollama；协调层未同步时主持牛内存局仍可述词 |
| 词库为空 | 检查 `data/who_is_spy/undercover_words.json` 或内置 `resource/who_is_spy/` |

## 实现

[`src/plugins/who_is_spy/`](../../../src/plugins/who_is_spy/)
