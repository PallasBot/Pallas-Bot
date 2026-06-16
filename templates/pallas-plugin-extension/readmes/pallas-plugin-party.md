# pallas-plugin-party

Pallas-Bot 4.0 官方扩展：**轻玩法**（`roulette` 轮盘赌、`drink` 喝酒）。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**。

```bash
uv sync --extra plugins-party
```

本包依赖 **`pallas-plugin-dream`**（醒酒联动醒梦）；`uv sync` 会自动拉取。

## 多进程分片

饮酒口令在插件中声明为**恒 fanout**，分片下各 worker 独立醉酒态；轮盘需牛牛为群管。

详见：[多进程分片](https://PallasBot.github.io/Pallas-Bot-Docs/architecture/bot-process-sharding)

## 功能说明

### 牛牛轮盘（roulette）

踢人/禁言轮盘；救援与补枪；醉酒时行为更随机。

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛轮盘 / 牛牛轮盘踢人 / 牛牛轮盘禁言 | 群内 | 启动（需牛牛为群管） |
| 牛牛开枪 | 群内 | 参与轮盘 |
| 牛牛救一下 [@用户] | 群内 | 解禁 |
| 牛牛补一枪 [@用户] | 群内 | 追加禁言 |

配置：[`src/pallas_plugin_roulette/config.py`](src/pallas_plugin_roulette/config.py)

### 牛牛喝酒（drink）

群内饮酒与醒酒，持久化醉酒度，影响聊天、轮盘、夺舍、做梦等。

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛喝酒 / 牛牛干杯 / 牛牛继续喝 | 群内 | 增加醉酒度，可能睡着 |
| 牛牛醒一醒 / 牛牛别喝了 | 群内 | 立即醒酒；本群在做梦时一并醒梦 |

### 排障

| 现象 | 处理 |
| --- | --- |
| 轮盘无法启动 | 确认牛牛为群管理员 |
| 喝酒无反应 | 群冷却或 ingress claim；分片下饮酒口令应全牛同响 |
| 一直不醒 | 发 `牛牛醒一醒` 或等待定时醒酒 |

## 文档

| 说明 | 链接 |
| --- | --- |
| 轮盘赌 | [文档站 · roulette](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/roulette) |
| 喝酒 | [文档站 · drink](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/drink) |

## 源码

- [`src/pallas_plugin_roulette/`](src/pallas_plugin_roulette/)
- [`src/pallas_plugin_drink/`](src/pallas_plugin_drink/)
