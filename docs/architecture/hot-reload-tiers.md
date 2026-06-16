# 热重载分级（L1 / L2 / L3）

> 与 [core-devx-roadmap · P3](core-devx-roadmap.md#p3--热重载分级) 对齐。  
> **现状**：L1 已成熟；L2/L3 以文档与 `reload_policy` 解析桩为主，CLI `pallas plugin reload` 尚未落地。

## 三级对照

| 级别 | 名称 | 变更内容 | 生效方式 | 现状 |
| --- | --- | --- | --- | --- |
| **L1** | 配置 | `config.py` 字段 → `webui.json` | `install_hot_reload_config` 保存后立即 reload | ✅ 默认路径 |
| **L2** | 元数据 | `PluginMetadata.extra`、help 索引、ingress route | 保存后重读声明 / 重建索引（**不**卸载 matcher） | ✅ `reload_plugin_metadata_l2()`；WebUI 插件配置保存对 `metadata`/`full` 策略触发 |
| **L3** | 插件代码 | Python 模块变更 | 受控 reload 或提示进程重启 | ❌ 默认需重启 |

## 明确不做

- NoneBot matcher 级热卸载/重载**不作为默认运维路径**（见 [pallas-cli.md](pallas-cli.md)）。
- 扩展 pip 包安装：`extension_install` 仍返回 `needs_restart`；与 **牛牛重启**（`pb_core`）共用调度 API。

## `reload_policy`（extra 可选键）

在 `PluginMetadata.extra` 声明插件作者期望的重载粒度（供能力总览与未来 CLI 读取）：

| 值 | 含义 |
| --- | --- |
| `config_only` | 仅 L1（**默认**；与现网一致） |
| `metadata` | L2：允许重读 extra / help / ingress，不卸载 matcher |
| `full` | L3：尝试重载模块；失败则提示重启 |

解析 API：`src.features.plugin_reload.reload_policy_from_metadata()`。

示例：

```python
extra={
    ...
    "reload_policy": "config_only",
}
```

## 运维入口

| 场景 | 推荐 |
| --- | --- |
| 改插件开关/阈值 | WebUI **插件** 页保存（L1） |
| 改命令权限 / CD | WebUI **命令权限** / **命令冷却**（L1） |
| 改 help / ingress 声明 | 插件 `reload_policy: metadata` 时 WebUI 保存可触发 L2；否则重启 |
| 改 Python 代码 | 重启 Bot；群内 **牛牛重启** 或 `pallas restart` |
| 安装官方扩展 | WebUI 插件商店；勾选「安装并重启」或手动重启 |

## 相关文档

- [WebUI 配置与热重载](../common/webui/README.md)
- [settings-storage.md](settings-storage.md)
- [core-devx-roadmap.md](core-devx-roadmap.md)
