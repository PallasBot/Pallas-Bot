# 牛牛决斗 `duel`

泰拉风味多幕决斗，含剧情事件、抢答与八角笼。需要群内对战玩法时安装本官方插件。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-duel
```

安装后重启 Bot。详见 [安装插件](../../guide/install-plugins.md)。

## 用法

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛决斗 @对手 [N幕\|N回合]` | 群内 | 向指定对手发起决斗 |
| `牛牛决斗 @牛A @牛B` | 群内 | 两只牛直接开打 |
| `八角笼牛 [N幕\|N回合]` | 群内 | 随机抽两只在线牛开战 |
| 按幕面提示回复干员名或关键词 | 群内 | 抢答环节限时作答 |
| `决斗事件重载` | 群内 | 重新加载剧情事件资源 |

精确口令与「何人可用」以群内 **牛牛帮助** 为准。同群同时仅一场。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `duel.duel` | 所有人 |
| `duel.cage` | 所有人 |
| `duel.reload_events` | 群管或号主 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

控制台对应插件页；字段以扩展仓 `pallas-plugin-duel` 的 `config.py` 为准。

干员头像等资源（主仓脚本）：

```bash
uv run python scripts/fetch_arknights_duel_data.py
```

## 排障

| 现象 | 处理 |
| --- | --- |
| 无法开战 | 同群同时仅一场；检查 @ 与牛是否在线 |
| 乱入无头像 | 执行上方资源脚本 |

## 源码

扩展仓 `pallas-plugin-duel`（不在主仓 `packages/`）。资源脚本：[`scripts/fetch_arknights_duel_data.py`](../../../scripts/fetch_arknights_duel_data.py)。

仓库：[Plugin-Duel](https://github.com/PallasBot/Plugin-Duel)

## 相关链接

- [命令权限](../../common/cmd_perm/README.md)
- [安装插件](../../guide/install-plugins.md)
