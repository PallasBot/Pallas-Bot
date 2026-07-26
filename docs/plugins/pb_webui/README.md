# Web 控制台 `pb_webui`

用浏览器查看和管理牛牛（配置、日志、插件商店、协议端入口等）。需要网页运维入口时依赖本插件；默认随本体加载。

**类型**：本体 core（默认加载）

## 安装

默认加载，无需单独安装。前端静态资源默认目录：`data/pb_webui/public-react`（React）。可用 `uv run pallas update webui` 拉取 Release 附带的构建产物。遗留 Vue 资源目录为 `data/pb_webui/public`，非默认。

## 用法

| 入口 | 说明 |
| --- | --- |
| `/pallas/` | 控制台页面 |
| `/pallas/api/*` | 控制台使用的状态与管理接口 |

默认端口见 `pallas.toml` 的 `[bootstrap] port`（常见为 `8088`）。登录口令在 `data/pallas_console/`；遗忘见 [FAQ](../../FAQ.md)。

无群内用户口令。面板说明见 [网页控制台](../../guide/web-console.md)。

## 命令权限（代码默认）

无群内命令。

## 配置

控制台相关行为见 [`packages/pb_webui/config.py`](../../../packages/pb_webui/config.py)。插件配置保存后写入 `data/pallas_config/webui.json`。热重载说明见 [webui](/common/webui)。

## 排障

| 现象 | 处理 |
| --- | --- |
| 无法登录 | 查启动日志中的初始口令与 `data/pallas_console/` |
| 页面空白 / 未部署前端 | 确认 `data/pb_webui/public-react` 有构建产物 |
| 插件配置没生效 | 确认对应插件已接入热重载配置 |

## 源码

[`packages/pb_webui/`](../../../packages/pb_webui/)

- `__init__.py`：控制台元数据
- `startup.py`：挂载页面与 API
- `config.py`：控制台配置
- `manager.py` / `public.py`：静态资源目录与挂载

## 相关链接

- [牛牛核心 pb_core](../pb_core/README.md)
- [在线统计 pb_stats](../pb_stats/README.md)
- [网页控制台指南](../../guide/web-console.md)
