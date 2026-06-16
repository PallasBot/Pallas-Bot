# pallas-plugin-social

Pallas-Bot 4.0 官方扩展：**打招呼**（`greeting`）与 **自动夺舍**（`take_name`）。

## 安装

需已安装 [Pallas-Bot](https://github.com/PallasBot/Pallas-Bot) **≥ 4.0**。

```bash
uv sync --extra plugins-social
```

## 功能说明

### 牛牛欢迎（greeting）

入群/好友欢迎、戳一戳回应；支持自定义欢迎图文。

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 新人入群 | 自动 | 默认或本群自定义欢迎 |
| 新好友 | 自动 | 默认或号主自定义欢迎 |
| 设置好友欢迎 / 清除好友欢迎 | 私聊 | 号主维护好友欢迎 |
| 设置群欢迎 / 清除群欢迎 | 群内 | 群管维护入群欢迎 |

| 命令 ID | 默认等级 |
| --- | --- |
| `greeting.set_friend_welcome` | bot_moderator |
| `greeting.clear_friend_welcome` | bot_moderator |
| `greeting.set_group_welcome` | group_moderator |
| `greeting.clear_group_welcome` | group_moderator |

配置：[`src/pallas_plugin_greeting/config.py`](src/pallas_plugin_greeting/config.py)；素材 **`data/greeting/`**，语音 **`resource/voices/`**。

与决斗 QTE 冲突时经 **`plugin_coord.duel`** 避让。

### 自动夺舍（take_name）

定时随机改牛牛群名片；醉酒时可能同步改被模仿群友名片。

| 触发 | 说明 |
| --- | --- |
| 定时任务 | 模仿群友名片并戳一戳 |
| 牛牛醉酒 | 可能「夺舍」改名 |

可在 WebUI **插件** 中开关；语料来自 core `repeater` 的 `MessageStore`。

### 排障

| 现象 | 处理 |
| --- | --- |
| 自定义欢迎未生效 | 确认命令权限与群管身份 |
| 夺舍从不改名 | 概率较低属正常；查插件是否被群关闭 |
| 改名片失败 | 牛牛需有改名片权限 |

## 文档

| 说明 | 链接 |
| --- | --- |
| 欢迎 | [文档站 · greeting](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/greeting) |
| 夺舍 | [文档站 · take_name](https://PallasBot.github.io/Pallas-Bot-Docs/plugins/take_name) |

## 源码

- [`src/pallas_plugin_greeting/`](src/pallas_plugin_greeting/)
- [`src/pallas_plugin_take_name/`](src/pallas_plugin_take_name/)
