# Reload 与 Activation

`reload_policy` 与 `activation_policy` 正交，不可混用。

| | `reload_policy` | `activation_policy` |
| --- | --- | --- |
| 视角 | 作者 / 插件内部 | 维护者 / 装包运维 |
| 触发 | WebUI 改配置或声明 | 安装、升级、卸载扩展 |
| 类型 | `config_only` \| `metadata` \| `full` | `hot-reloadable` \| `workers-restart` \| `full-restart` |
| 定义 | `pallas.core.plugin_reload.metadata` | `plugin_matrix.ActivationPolicy` |

## 热重载三级

| 级别 | 变更内容 | 生效方式 | 现状 |
| --- | --- | --- | --- |
| 配置 | `config.py` 字段 → `webui.json` | `install_hot_reload_config` 保存后立即 reload | 默认路径 |
| 元数据 | `PluginMetadata.extra`、help、ingress | 重读声明 / 重建索引（不卸载 matcher） | WebUI 保存对 `metadata`/`full` 触发；`pallas plugin reload` |
| 代码 | Python 模块 | 受控 reload 或提示重启 | 默认需重启 |

明确不做：

- NoneBot matcher 级热卸载不作为默认运维路径
- 已加载扩展包的代码热更（更新后须重启；unified 下**首次安装**可热加载）
- 社区插件 git 更新 / 卸载的代码级热更

## `reload_policy`

| 值 | 适用变更 | 运行时行为 |
| --- | --- | --- |
| `config_only` | 开关、频率、文案等配置字段（**默认**） | 保存即可 |
| `metadata` | 帮助、权限、ingress 声明 | 重建元数据索引 |
| `full` | 需模块级重载的结构 | 尝试 `importlib.reload`；失败则提示重启 |

```python
extra={
    ...
    "reload_policy": "config_only",
}
```

代码级逻辑变更仍按进程重启理解。

## `activation_policy`

运维视角的装包生效策略，独立于作者声明的 `reload_policy`：

| 值 | 含义 | 典型场景 |
| --- | --- | --- |
| `hot-reloadable` | 优先运行时热加载 | 纯命令型、无 hub 路由 / 后台任务 |
| `workers-restart` | 分片优先 workers-only；单进程整进程重启 | 主要影响 worker 命令处理 |
| `full-restart` | 全栈重启 | hub 路由、协议端、跨角色挂载 |

### 社区插件（`local/plugins/<id>/`）

| 操作 | activation_policy | unified（不勾重启） | shard（勾重启） |
| --- | --- | --- | --- |
| 首次安装 | `hot-reloadable` | 热加载 | 提示待重启；勾选则 workers-only |
| git 更新 | `workers-restart` | 提示待重启 | workers-only |
| 卸载 | `full-restart` | 提示待重启 | workers-only |

前提：`[bootstrap].extra_plugin_dirs` 含 `"local/plugins"`。

### 官方插件建议

| 扩展 | activation_policy |
| --- | --- |
| `pallas-plugin-draw` / `bot-status` | `hot-reloadable` |
| `duel` / `who-is-spy` / `dream` / `ai-media` | `workers-restart` |
| `protocol` / `maa` | `full-restart` |

## 并存示例

```text
reload_policy = metadata
activation_policy = workers-restart
```

含义：WebUI 改声明可重建索引；新装 / 升级包仍需 worker 重启才真正生效。

## 运维入口

| 场景 | 推荐 |
| --- | --- |
| 改插件开关 / 频率 | WebUI 插件页保存 |
| 改命令权限 / CD | WebUI 命令权限 / 冷却页 |
| 改 help / ingress 声明 | `reload_policy: metadata` 时保存可重建索引；或 `pallas plugin reload <name>` |
| 改 Python 代码 | 重启 Bot（`full` 可尝试 reload，失败则重启） |
| 安装官方插件 | 插件商店；勾选「安装并重启」或手动重启 |
| 安装 / 更新社区插件 | 社区商店；unified 首次可热载，**更新须重启** |

## 规则

| 角色 | 规则 |
| --- | --- |
| 作者 | 按变更粒度选 `reload_policy`；勿把代码变更标成可热载 |
| 维护者 | 装包看 `activation_policy`；支持配置热载 ≠ 装包免重启 |

## 相关

- [元数据](metadata.md)
- [插件治理](/developer/architecture/plugin-governance)
- [热重载前检查清单](/maintainer/operate/hot-reload-pre-reload-checklist)
- [配置存储](/developer/architecture/config-storage)
