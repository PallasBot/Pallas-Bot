<div align="center">
  <img alt="Pallas-Bot" src="https://user-images.githubusercontent.com/18511905/195892994-c1a231ec-147a-4f98-ba75-137d89578247.png" width="360" height="270" />
</div>

# pallas-plugin-duel

Pallas-Bot 4.0 官方扩展：**牛牛决斗**。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**。

```bash
# 在本体项目中
uv sync --extra plugins-duel

# 或单独安装本包
uv pip install pallas-plugin-duel
```

开发联调：clone 本仓库后 `uv pip install -e .`（`pyproject.toml` 可配置本体 path 依赖）。

## 多进程分片

Pallas-Bot 支持单进程，也支持 **hub + 多个 worker** 的多进程部署。启用分片时：

- **hub 与每个 worker 须安装相同版本的本扩展包**；
- 各进程共享同一路径的 **`data/`**（注册表、协调状态、WebUI 落盘等）；
- 跨进程互斥与状态同步依赖 Redis 协调层（配置见文档站）。

本插件通过本体 **`plugin_coord`** 与启动时的 **`register_duel_coord()`** / **`register_fleet_probe()`** 接入协调层；未安装扩展时不影响 core 插件运行。

详见：[多进程分片 · 架构说明](https://PallasBot.github.io/Pallas-Bot-Docs/maintainer/deploy/sharded)

## 功能说明

泰拉风味多幕决斗：事件包、干员/关键词 QTE、双牛八角笼、胜负惩罚。

### 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛决斗 @对手 [N幕\|N回合] | 群内 | 对人或单牛 |
| 牛牛决斗 @牛A @牛B | 群内 | 双牛对决 |
| 八角笼牛 [N幕\|N回合] | 群内 | 随机两只在线牛牛 |
| 按幕面提示答干员名/关键词 | 群内 | QTE 抢答 |
| 决斗事件重载 | 群内 | 热更新事件包（群管） |

### 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `duel.duel` | 所有人 |
| `duel.cage` | 所有人 |
| `duel.reload_events` | 群管/群主 |

### 配置

WebUI **插件 → duel**，或本仓库 [`config.py`](src/pallas_plugin_duel/config.py)。事件包约定见 [`event_packs/README.md`](src/pallas_plugin_duel/event_packs/README.md)。

干员资源同步（在本体仓库执行）：

```bash
uv run python scripts/fetch_arknights_duel_data.py
```

### 排障

| 现象 | 处理 |
| --- | --- |
| 无法开战 | 同群仅一场；检查 @ 与在线牛 |
| 乱入无头像 | 执行资源脚本补 `resource/arknights/avatars` |

## 文档

| 说明 | 链接 |
| --- | --- |
| 牛牛决斗 · 用户文档 | [文档站 · duel](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/duel) |
| 插件开发入门 | [develop/plugin/getting-started](https://PallasBot.github.io/Pallas-Bot-Docs/develop/plugin/getting-started) |
| 多进程分片 | [分片部署](https://PallasBot.github.io/Pallas-Bot-Docs/maintainer/deploy/sharded) |

## 源码

实现位于本仓库 [`src/pallas_plugin_duel/`](src/pallas_plugin_duel/)。
