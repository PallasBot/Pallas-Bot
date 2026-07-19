<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="牛牛欢迎">
</p>

<h1 align="center">牛牛欢迎 greeting</h1>

<p align="center">为新好友和新成员发送欢迎内容，并支持自定义。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `新人入群` | 自动 | 发送默认或本群自定义欢迎。 |
| `新好友添加` | 自动 | 发送默认或好友自定义欢迎。 |
| `设置好友欢迎` / `清除好友欢迎` | 私聊 | 维护好友欢迎内容。 |
| `设置群欢迎` / `清除群欢迎` | 群内 | 维护当前群入群欢迎。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `greeting.set_friend_welcome` | 号主 |
| `greeting.clear_friend_welcome` | 号主 |
| `greeting.set_group_welcome` | 群管/群主 |
| `greeting.clear_group_welcome` | 群管/群主 |

## 配置项

> 可在控制台对应插件页中修改。

欢迎相关配置见 [`packages/greeting/config.py`](../../packages/greeting/config.py)。欢迎素材和持久化内容通常落在 `data/greeting/`。

## 排障

| 现象 | 处理 |
| --- | --- |
| 自定义欢迎没生效 | 确认当前身份有权限，且内容保存成功。 |
| 图片欢迎失败 | 检查素材下载、保存路径和发送权限。 |

## 实现

源码位置：[`packages/greeting/`](../../packages/greeting/)

关键文件：

- [`__init__.py`](../../packages/greeting/__init__.py)：注册欢迎元数据和权限说明。
- [`commands.py`](../../packages/greeting/commands.py)：处理设置和清除欢迎内容。
- [`config.py`](../../packages/greeting/config.py)：定义欢迎行为相关配置。

实现要点：

- 好友欢迎和群欢迎是两套独立内容，触发场景和权限也不同。
- 自动欢迎会优先使用用户或群里保存过的自定义内容。
- 这类欢迎属于事件驱动，不依赖普通群聊命令触发。

## 相关链接

- [命令权限说明](../common/cmd_perm/README.md)
