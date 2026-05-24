# greeting（牛牛欢迎）

入群/好友欢迎、戳一戳回应；支持自定义欢迎图文。

## 用户命令

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 新人入群 | 自动 | 默认或本群自定义欢迎 |
| 新好友 | 自动 | 默认或号主自定义欢迎 |
| 设置好友欢迎 / 清除好友欢迎 | 私聊 | 号主维护好友欢迎 |
| 设置群欢迎 / 清除群欢迎 | 群内 | 群管维护入群欢迎 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `greeting.set_friend_welcome` | bot_moderator |
| `greeting.clear_friend_welcome` | bot_moderator |
| `greeting.set_group_welcome` | group_moderator |
| `greeting.clear_group_welcome` | group_moderator |

## 配置

[`config.py`](../../../src/plugins/greeting/config.py)（如 `enable_kick_ban`）。素材与持久化目录 **`data/greeting/`**；语音资源 **`resource/voices/`**。

## 排障

| 现象 | 处理 |
| --- | --- |
| 自定义未生效 | 确认命令权限与群管身份 |
| 图片失败 | 检查下载与存储路径 |

## 实现

[`src/plugins/greeting/`](../../../src/plugins/greeting/)
