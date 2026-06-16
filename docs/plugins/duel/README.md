# duel（牛牛决斗）

> **官方扩展**：`pallas-plugin-duel`（`uv sync --extra plugins-duel`）

泰拉风味多幕决斗：剧情事件、抢答、双牛八角笼、胜负惩罚。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛决斗 @对手 [N幕\|N回合] | 群内 | 挑战一名对手 |
| 牛牛决斗 @牛A @牛B | 群内 | 两只牛牛对决 |
| 八角笼牛 [N幕\|N回合] | 群内 | 随机两只在线牛牛 |
| 按幕面提示答干员名/关键词 | 群内 | 限时抢答 |
| 决斗事件重载 | 群内 | 重新加载剧情包（群管） |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `duel.duel` | everyone |
| `duel.cage` | everyone |
| `duel.reload_events` | group_moderator |

## 配置

WebUI **插件 → 牛牛决斗** 或 [`config.py`](../../../src/plugins/duel/config.py)。

干员头像等资源：

```bash
uv run python scripts/fetch_arknights_duel_data.py
```

## 排障

| 现象 | 处理 |
| --- | --- |
| 无法开战 | 同群同时仅一场；检查 @ 与牛牛是否在线 |
| 乱入无头像 | 执行上方资源脚本 |

## 实现

[`src/plugins/duel/`](../../../src/plugins/duel/)
