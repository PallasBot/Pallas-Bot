<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="重新上号">
</p>

<h1 align="center">重新上号 relogin_bot</h1>

<p align="center">让号主重新拉起协议端，并获取登录二维码。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="控制台插件商店" src="https://img.shields.io/badge/%E6%8E%A7%E5%88%B6%E5%8F%B0-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--protocol-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-protocol`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛重新上号 [QQ]` | 私聊 | 号主重启自己的协议端实例。 |
| `创建牛牛 …` | 私聊 | 超管创建新的牛牛实例。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `relogin.relogin` | 号主 |
| `relogin.create` | 仅超管 |

## 配置项

> 可在控制台对应插件页中修改。

这个功能依赖 `pb_protocol` 和对应协议端发行包，具体实例与号主配置可在控制台的实例与连接页面完成。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无二维码 | 检查协议端日志与 `data/` 下的二维码文件。 |
| 无权限 | 确认当前用户已加入 `admins` 或具有超管权限。 |

## 实现

源码位置：官方插件扩展仓 `pallas-plugin-protocol` 中的 `relogin_bot` 插件目录

关键文件：

- 扩展仓 `relogin_bot` 插件入口文件：注册重新上号和创建牛牛命令。
- 协议端实例控制文件：负责重启实例与产出二维码。
- 控制台实例配置逻辑：负责初始化号主与账号归属。

实现要点：

- 重新上号本质上是协议端实例操作，所以强依赖 `pb_protocol`。
- `创建牛牛` 不只是开号，还会顺带写入号主信息。
- 私聊触发是主路径，避免群内泄漏二维码和敏感操作结果。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
- [协议端管理说明](../pb_protocol/README.md)
- [重新上号插件仓库](https://github.com/TogetsuDo/pallas-plugin-protocol)
