<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛卧底">
</p>

<h1 align="center">牛牛卧底 who_is_spy</h1>

<p align="center">群内发起谁是卧底，支持讨论、匿名投票和复盘。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="控制台插件商店" src="https://img.shields.io/badge/%E6%8E%A7%E5%88%B6%E5%8F%B0-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--who--is--spy-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-who-is-spy`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛卧底` | 群内 | 创建房间。 |
| `牛牛加入` / `牛牛退出` | 群内 | 在筹备阶段加入或退出。 |
| `牛牛发身份 [潜藏人数] [白板] [暗牌\|明牌]` | 群内 | 房主开局并下发词语。 |
| `@牛牛 + 描述` | 群内 | 讨论阶段记为述词。 |
| `牛牛投票` | 群内 | 房主提前开始投票。 |
| 私聊回复数字序号或 `0` | 私聊 | 进行匿名投票，`0` 表示弃权。 |
| `牛牛局势` / `牛牛结束` | 群内 | 查看局势或结束房间。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `who_is_spy.open` | 所有人 |
| `who_is_spy.join` | 所有人 |
| `who_is_spy.start` | 所有人 |
| `who_is_spy.status` | 所有人 |
| `who_is_spy.end` | 所有人 |

## 配置项

> 可在控制台对应插件页中修改。

牛牛卧底的常用配置包括最少/最多人数、默认卧底和白板数量、是否暗牌、述词字数上限等。

词库文件默认保存在 `data/who_is_spy/undercover_words.json`，首次会从内置资源复制，后续可自行增补。

## 排障

| 现象 | 处理 |
| --- | --- |
| 收不到词语或投票私聊 | 先加牛牛好友；如开启邮箱兜底，也可检查 QQ 邮箱。 |
| 本群已有房间 | 同群只允许一局进行中，可发送 `牛牛结束` 或等待自动清理。 |
| 述词无回复 | 多牛同群时，需要 `@` 本局主持牛。 |
| 词库为空 | 检查 `data/who_is_spy/undercover_words.json` 或内置 `resource/who_is_spy/`。 |

## 实现

源码位置：官方插件扩展仓 `pallas-plugin-who-is-spy`

关键文件：

- 扩展仓 `src/pallas_plugin_who_is_spy/__init__.py`：注册命令与帮助元数据。
- 扩展仓房间与回合逻辑文件：管理玩家列表、回合推进、投票与结算。
- 词库资源与存储文件：负责默认词对初始化和持久化。

实现要点：

- 这是一个群内长流程游戏，房间状态会跨多条消息持续存在。
- 讨论阶段和投票阶段都依赖主持牛，因此多牛同群时会有明确归属。
- 发词和投票说明优先私聊投递，必要时可退回到邮箱兜底。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [牛牛卧底插件仓库](https://github.com/TogetsuDo/pallas-plugin-who-is-spy)
