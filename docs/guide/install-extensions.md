# 安装官方扩展

4.0 起，决斗、MAA、谁是卧底等玩法迁到 **官方扩展 pip 包**；默认 slim 镜像只带核心插件。

## 三种安装方式

| 方式 | 适用场景 |
| --- | --- |
| **WebUI 插件商店** | 有 `pyproject.toml` 且环境有 `uv`（源码部署、开发机） |
| **命令行** | 同上，或脚本自动化 |
| **`local/plugins/`** | Docker 精简镜像、无 uv、或站点自研插件 |

## WebUI 一键安装

1. 登录控制台 → **插件商店**（或插件目录页入口）
2. 找到扩展包 → **一键安装**
3. **重启 Bot** 后插件才会加载（支持「安装并重启」时可直接点）

::: details 何时没有「一键安装」按钮？
- 运行目录没有 `pyproject.toml`（典型 Docker 只读镜像）
- 容器 / 系统 PATH 里没有 `uv`

此时请用下方命令行，或把插件目录放到 `local/plugins/`。
:::

## 命令行安装

在仓库根目录：

```bash
# 示例：决斗
uv sync --extra plugins-duel

# 示例：MAA
uv sync --extra plugins-maa
```

扩展包名与 extra 对照见控制台 **插件商店** 卡片，或 [插件索引](../plugins/README.md)。

也可用 CLI：

```bash
uv run pallas ext install pallas-plugin-duel
```

## 站点自有插件（local）

不经过 pip、直接放代码：

```toml
# config/pallas.toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

目录结构：`local/plugins/<插件名>/`（标准 NoneBot 插件）。与官方扩展 **同名时 local 优先**。

详见 [站点定制与扩展](../architecture/site-customization-and-updates.md)。

## 卸载

- WebUI 插件商店 → **卸载**（需已 pip 安装）
- 或：`uv run pallas ext uninstall <package>`

卸载 pip 包 **不会** 删除 `local/plugins/` 里的副本。

::: tip 下一步
扩展装好后，到 [插件手册](../plugins/README.md) 查口令与配置项。
:::
