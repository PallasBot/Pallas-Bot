<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="MAA 远控">
</p>

<h1 align="center">MAA 远控 maa</h1>

<p align="center">在 QQ 里给已绑定的 MAA 设备下发任务并接收结果。</p>

<p align="center">
  <img alt="官方插件" src="https://img.shields.io/badge/%E5%AE%98%E6%96%B9%E6%8F%92%E4%BB%B6-FE7D37">
  <img alt="WebUI 插件商店" src="https://img.shields.io/badge/WebUI-%E6%8F%92%E4%BB%B6%E5%95%86%E5%BA%97-4EA94B">
  <img alt="安装命令" src="https://img.shields.io/badge/uv%20run%20pallas%20ext%20install%20pallas--plugin--maa-586069">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

可在控制台插件商店安装，或执行 `uv run pallas ext install pallas-plugin-maa`。

## 怎么使用

| 口令 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `牛牛绑定MAA` | 私聊 | 绑定当前 QQ 到自己的 MAA 设备。 |
| `牛牛MAA状态` | 私聊 / 群内 | 查看绑定情况、当前设备与队列状态。 |
| `牛牛切换MAA设备` | 私聊 | 在多台设备之间切换远控目标。 |
| `牛牛长草`、`牛牛作战`、`牛牛公招`、`牛牛基建`、`牛牛截图`、`牛牛停止` | 群内 | 下发常用远控任务。 |
| `牛牛MAA任务 <type> [params]` | 群内 | 手动指定任务类型和参数。 |

> 详细用法、限制条件和可用范围以帮助为主。

上手顺序：先配置对外访问地址，再在 MAA 中填写帮助页 URL 和 QQ 标识，之后私聊绑定设备、在群里发任务口令。

### 多台设备

| 口令 | 说明 |
| --- | --- |
| `牛牛MAA状态` | 列表与当前选用 |
| `牛牛切换MAA设备` | 改远控目标 |
| `牛牛MAA设备名` | 设置别名 |
## 命令权限

| 命令 ID | 默认等级 | 说明 |
| --- | --- | --- |
| `maa.bind` | 所有人 | 牛牛绑定MAA |
| `maa.switch_device` | 所有人 | 牛牛切换MAA设备 |
| `maa.device_alias` | 所有人 | 牛牛MAA设备名 |
| `maa.control` | 所有人 | 牛牛长草 / 牛牛作战等远控口令 |
| `maa.raw_task` | 所有人 | 牛牛MAA任务 |
| `maa.clear_queue` | 所有人 | 牛牛清空MAA队列 |
| `maa.status` | 所有人 | 牛牛MAA状态 |

可在 WebUI 插件页或「通用配置 → 命令权限」覆盖。

## 配置项

> 可在控制台对应插件页中修改。

一般只需 **对外访问地址**（WebUI **通用配置 → 外部服务地址** 或插件配置）。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `maa_public_base_url` | 空 | 对外 HTTP 基址 |
| `maa_attach_screenshot` | true | 指令后附加截图 |
| `maa_combat_auto_prepare` | true | 作战前自动排队关卡设置 |

完整键以扩展仓 `pallas-plugin-maa` 的 `config.py` 为准。

## 排障

| 现象 | 处理 |
| --- | --- |
| 未检测到轮询 | MAA 端点不可达或 URL 错误；多机部署须各实例共用 `data/` |
| 下发后无任务 | 未绑定或用户标识符非 QQ；查 `牛牛MAA状态` |
| 队列有、MAA 无 | 设备 id 与「当前选用」不一致；可清空队列重试 |
| 截图失败 | 调大反代上传大小限制 |

## 实现

源码位置：扩展仓 `pallas-plugin-maa`

关键文件：

- 扩展仓 `src/pallas_plugin_maa/__init__.py`：注册口令、权限与帮助元数据。
- 扩展仓 `src/pallas_plugin_maa/tasks.py`：把群内口令映射成具体任务类型与参数。
- 扩展仓 `src/pallas_plugin_maa/http_api.py`、`http_routes.py`：实现与 MAA 设备的 HTTP 协议交互。
- 扩展仓 `src/pallas_plugin_maa/store.py`：保存绑定关系、设备选择和任务队列。

实现要点：

- 插件通过 HTTP 协议和 MAA 设备通信，设备轮询取任务，Bot 再接收执行状态与截图等结果。
- 顺序任务会排队执行，截图、停止等即时任务可以插队，所以同一设备上的任务顺序是可控的。
- 群内远控命令会做同群 claim，避免多牛部署时同一条消息被多只牛同时接单；私聊绑定和切换设备不受这个限制。

## 相关链接

- [插件文档索引](../README.md)
- [命令权限说明](../common/cmd_perm/README.md)
- [MAA 插件仓库](https://github.com/TogetsuDo/pallas-plugin-maa)
- [MAA 远程控制协议](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)
