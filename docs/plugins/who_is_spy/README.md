# who_is_spy（牛牛卧底）

> **官方扩展**：`pallas-plugin-who-is-spy`（`uv sync --extra plugins-who-is-spy`）

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

WebUI **插件 → 牛牛卧底** 或 [`config.py`](../../../src/plugins/who_is_spy/config.py)。常用项：最少/最多人数、默认卧底与白板数、是否暗牌、述词字数上限等。

**私聊与邮箱**：发词/投票说明优先好友私聊；失败时尝试临时会话；仍失败且开启邮箱兜底时，复用 **牛牛状态** 的 SMTP 向 `{QQ号}@qq.com` 发信。

词库：`data/who_is_spy/undercover_words.json`（首次从内置 resource 复制，之后自动合并新增词对）。编辑后重启 Bot 生效。

## 排障

| 现象 | 处理 |
| --- | --- |
| 收不到词语/投票私聊 | 加牛牛好友；或查 QQ 邮箱；确认牛牛状态 SMTP 已配置 |
| 私聊「你的词：」后无字 | 非白板玩法，属投递失败；加好友、查邮箱或看开局提示里的未达名单 |
| 本群已有房间 | 多机部署下同群互斥；「牛牛结束」或等局后自动清理 |
| @牛牛 述词无回复 | 多牛同群须 @ **本局主持牛**（发「词已私聊」的那只） |
| 词库为空 | 检查 `data/who_is_spy/undercover_words.json` 或内置 `resource/who_is_spy/` |

## 实现

[`src/plugins/who_is_spy/`](../../../src/plugins/who_is_spy/)
