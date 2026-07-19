<div align="center">
  <img alt="Pallas-Bot" src="https://user-images.githubusercontent.com/18511905/195892994-c1a231ec-147a-4f98-ba75-137d89578247.png" width="360" height="270" />
</div>

# pallas-plugin-dream

Pallas-Bot 4.0 官方扩展：**牛牛做梦**（群内旁路、分片漂移）。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**。

```bash
uv sync --extra plugins-dream
```

开发联调：clone 本仓库后 `uv pip install -e .`。

## 多进程分片

- **hub 与每个 worker 须安装相同版本**；共享 **`data/`** 与 Redis 协调层。
- 梦话漂流经本体 **`plugin_coord.dream`**；未安装扩展时不影响 core。

详见：[多进程分片](https://PallasBot.github.io/Pallas-Bot-Docs/maintainer/deploy/sharded)

## 功能说明

做梦期间推送梦话：跨群漂流、历史梦、画画归档图、复读已学句；醉酒时更密且可联动夺舍。

### 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛做梦 | 群内 | 进入做梦约 5～15 分钟 |
| 牛牛醒梦 / 牛牛别做梦 | 群内 | 结束做梦 |
| 牛牛醒一醒 | 群内 | 醒酒时亦会醒梦（见本体 core `drink`） |

### 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `dream.ban_cleanup` | 群管或号主 |

（与复读共用「不可以」清理梦库，权限见帮助详情。）

### 配置

WebUI **插件 → dream**，或本仓库 [`config.py`](src/pallas_plugin_dream/config.py)：`dream_worker_sleep_*`、`dream_drift_queue_tick_probability`、`dream_message_retention_days` 等。

### 排障

| 现象 | 处理 |
| --- | --- |
| 无梦话 | 确认已做梦、冷却未挡；他群无做梦则无漂流 |
| 梦库过大 | 运维可调用库清理逻辑 |

## 文档

| 说明 | 链接 |
| --- | --- |
| 牛牛做梦 · 用户文档 | [文档站 · dream](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/dream) |
| 插件开发入门 | [develop/plugin/getting-started](https://PallasBot.github.io/Pallas-Bot-Docs/develop/plugin/getting-started) |

## 源码

[`src/pallas_plugin_dream/`](src/pallas_plugin_dream/)
