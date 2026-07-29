# 重新上号 `relogin_bot`

号主私聊重新拉起协议端并获取登录二维码；超管可创建新牛实例。需要掉线重登或批量建号时使用（与 [pb_protocol](../pb_protocol/README.md) 同属 `pallas-plugin-protocol`）。

**类型**：官方插件（需安装）

## 安装

控制台插件商店，或：

```bash
uv run pallas ext install pallas-plugin-protocol
```

## 用法

| 命令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛重新上号 [QQ]` | 私聊 | 号主重启自己的协议端实例 |
| `创建牛牛 …` | 私聊 | 超管创建新的牛牛实例 |

精确命令与「何人可用」以 **牛牛帮助** / 私聊权限为准。主路径走私聊，避免群内泄漏二维码。

## 命令权限（代码默认）

| 命令 ID | 默认等级 |
| --- | --- |
| `relogin.relogin` | 号主 |
| `relogin.create` | 仅超管 |

实际生效等级以控制台「命令权限」为准。面向用户的 usage 不要写死角色名。

## 配置

依赖 `pb_protocol` 与协议端发行包。实例与号主在控制台 **实例与连接** 配置。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无二维码 | 查协议端日志与 `data/` 下二维码文件 |
| 无权限 | 确认当前用户已在 `admins` 或具备超管权限 |

## 源码

扩展仓 `pallas-plugin-protocol` 中的 `relogin_bot` 目录。

仓库：[Plugin-Protocol](https://github.com/PallasBot/Plugin-Protocol)

## 相关链接

- [协议端 pb_protocol](../pb_protocol/README.md)
- [命令权限](../../common/cmd_perm/README.md)
