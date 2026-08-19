# 官方插件运维

用户向的安装、商店界面和插件对照见 [安装插件](/guide/install-plugins)。本页只处理无图形界面、精简 Docker 镜像、分片和回滚等运维场景。

## 适用场景

- 通过 SSH、CI/CD 或脚本批量安装、更新或卸载官方插件。
- 精简 Docker 镜像没有现场装包条件，需要在构建期预装插件。
- 分片部署中需要确认插件是否在目标 worker 生效。
- 排查 `local/plugins/` 同名副本、pip 包和运行态加载结果。

`core` 随主仓启动；官方插件以 PyPI 包安装；站点私有与社区插件通常位于 `local/plugins/`。

## CLI 管理

在 Pallas-Bot 工作目录中执行：

```bash
uv run pallas ext list
uv run pallas ext install pallas-plugin-duel --restart
uv run pallas ext update pallas-plugin-duel --restart
uv run pallas ext uninstall pallas-plugin-duel --restart
```

CLI 适合无图形界面、CI/CD 或批量初始化。日常使用控制台时，仍优先在 **插件商店** 完成装、卸和更新。

## 运行前提

商店一键安装与 CLI 共用当前 Pallas-Bot 运行环境：需要完整工作目录、可执行的 `uv` 和可访问的 PyPI。

```bash
uv --version
uv run pallas --help
```

::: warning 注意：精简 Docker 镜像
精简镜像通常没有容器内现场装包条件。构建镜像时使用 `uv sync --extra ...` 预装插件；运行后安装则使用具备 PyPI 访问能力的控制台商店。
:::

## 分片与加载状态

官方插件安装完成后重启 Bot，再确认：

1. 控制台商店显示「已加载」，或 `pallas ext list` 显示 `installed=yes`。
2. 群里发送 `牛牛帮助`，确认新增能力已出现。
3. 有配置页时，控制台页面可打开并读到配置。

::: warning 注意：分片加载
部分插件只在 worker 侧运行。控制台的加载态来自 hub 聚合的 worker 元数据；排查时确认目标 worker 已重启并已加载插件。
:::

## 卸载与回滚

优先在 **插件商店** 卸载；无 UI 时使用 `pallas ext uninstall`。

- 卸载 pip 包不会删除 `local/plugins/` 中的同名副本。
- 安装、卸载或升级后都重启 Bot。
- 插件仍被加载时，检查 `local/plugins/` 是否覆盖了同名 pip 包。

## 相关阅读

- [安装插件](/guide/install-plugins)
- [网页控制台](/guide/web-console)
- [CLI 参考](/maintainer/reference/cli)
- [插件治理](/maintainer/operate/plugin-governance)
