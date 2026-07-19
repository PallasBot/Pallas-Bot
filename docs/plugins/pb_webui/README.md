<p align="center">
  <img src="../assets/brand-avatar.png" width="220" height="220" alt="Web 控制台">
</p>

<h1 align="center">Web 控制台 pb_webui</h1>

<p align="center">用浏览器查看和管理牛牛。</p>

<p align="center">
  <img alt="本体 core" src="https://img.shields.io/badge/%E6%9C%AC%E4%BD%93%20core-4B5563">
  <img alt="默认加载" src="https://img.shields.io/badge/%E9%BB%98%E8%AE%A4%E5%8A%A0%E8%BD%BD-4EA94B">
  <img alt="版本 4.0.0" src="https://img.shields.io/badge/%E7%89%88%E6%9C%AC-4.0.0-2563EB">
</p>

## 安装方式

默认加载，无需单独安装。

## 怎么使用

| 入口 / 触发 | 场景 | 说明 |
| --- | --- | --- |
| `/pallas/` | 浏览器 | 打开控制台页面。 |
| `/pallas/api/*` | HTTP | 控制台使用的状态和管理接口。 |

> 详细用法、限制条件和可用范围以帮助为主。

## 命令权限

无群内命令。

## 配置项

> 可在控制台对应插件页中修改。

控制台口令保存在 `data/pallas_console/`。前端静态资源、热重载配置和控制台行为主要由 [`packages/pb_webui/config.py`](../../packages/pb_webui/config.py) 与启动流程控制。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无法登录 | 检查启动日志里的初始口令和控制台口令目录。 |
| 插件配置没生效 | 确认对应插件实现了热重载配置接入。 |

## 实现

源码位置：[`packages/pb_webui/`](../../packages/pb_webui/)

关键文件：

- [`__init__.py`](../../packages/pb_webui/__init__.py)：注册控制台元数据。
- [`startup.py`](../../packages/pb_webui/startup.py)：挂载控制台页面和 API。
- [`config.py`](../../packages/pb_webui/config.py)：定义控制台相关配置。

实现要点：

- 控制台本身不是群内功能，而是浏览器侧的维护入口。
- 页面和接口是一起挂载的，很多插件配置都通过这里统一写回。
- 控制台也是很多运维能力的主入口，例如日志、数据库概览和插件配置。

## 相关链接

- [牛牛核心](../pb_core/README.md)
- [在线统计](../pb_stats/README.md)
