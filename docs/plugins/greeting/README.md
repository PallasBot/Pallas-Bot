# 牛牛欢迎 `greeting`

为新好友和新成员发送欢迎内容，并支持自定义。需要入群 / 加好友自动欢迎，或维护欢迎文案时用本插件。

**类型**：本体 core（默认加载）

## 安装

默认加载，无需单独安装。

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| 新人入群 | 自动 | 默认或本群自定义欢迎 |
| 新好友添加 | 自动 | 默认或好友自定义欢迎 |
| `设置好友欢迎` / `清除好友欢迎` | 私聊 | 维护好友欢迎 |
| `设置群欢迎` / `清除群欢迎` | 群内 | 维护当前群入群欢迎 |

精确命令与「何人可用」以群内 **牛牛帮助** 为准。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `greeting.set_friend_welcome` | 号主 |
| `greeting.clear_friend_welcome` | 号主 |
| `greeting.set_group_welcome` | 群管或号主 |
| `greeting.clear_group_welcome` | 群管或号主 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

控制台对应插件页。见 [`packages/greeting/config.py`](../../../packages/greeting/config.py)。欢迎素材通常落在 `data/greeting/`。

保存后写入 `data/pallas_config/webui.json`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 自定义欢迎没生效 | 确认有权限且内容已保存 |
| 图片欢迎失败 | 检查素材路径与发送权限 |

## 源码

[`packages/greeting/`](../../../packages/greeting/)

- `__init__.py`：元数据与权限
- `commands.py`：设置 / 清除
- `config.py`：欢迎行为配置

好友欢迎与群欢迎相互独立；自动欢迎优先用已保存的自定义内容。

## 相关链接

- [命令权限](../../common/cmd_perm/README.md)
