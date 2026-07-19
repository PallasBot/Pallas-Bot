# 五、路径、数据与资源

## 5.1 约定

| 类型 | 位置 | Helper |
| --- | --- | --- |
| 群/用户/牛/部署级结构化状态 | DB 内 `plugin_storage` 字段 | `GroupPluginStorage("my_plugin", group_id)` + `extra["plugin_storage"]` |
| 大文件、缓存、导出 | `data/<plugin_name>/` | `plugin_data_dir("my_plugin")` |
| 静态资源 | `resource/<subdir>/` | `resource_dir("voices")` 等 |

```python
from pallas.api.storage import GroupPluginStorage, plugin_storage_list, plugin_storage_row
from pallas.api.paths import plugin_data_dir, resource_dir

# 结构化群状态（须在 PluginMetadata.extra 声明键）
store = GroupPluginStorage("my_plugin", group_id)
await store.set("my_state", {"n": 1})

# 非结构化文件
CACHE = plugin_data_dir("my_plugin")
VOICES = resource_dir("voices")
```

**不要**硬编码 `data/`、`resource/` 相对路径字符串；工作目录变化会导致漂移。

现行说明优先看 [配置与 WebUI](../../developer/plugin-development/config-and-webui.md) 与 [Golden Plugin](../../developer/plugin-development/golden-plugin.md)。

## 5.2 何时用哪种

| 场景 | 推荐 |
| --- | --- |
| 群开关、计数、小 JSON 状态 | `plugin_storage` + `GroupPluginStorage` |
| 图片/语音文件、日志、导出 zip | `plugin_data_dir` |
| 只读素材 | `resource_dir` |
| 跨群关系、审计、复杂查询 | `pallas.core.foundation.db` repository（内置插件用） |

`data/<plugin_name>/` 仍按插件隔离，便于备份与清理。

## 5.3 数据库

持久化优先走 `pallas.core.foundation.db` repository 模式；表结构与迁移遵循仓库现有插件（如 blacklist、request_handler）。新表需考虑 PostgreSQL 与 CI。

## 5.4 测试中的路径

测试可使用临时目录或 fixture；参考 `tests/plugins/` 下既有写法，避免写真实 `data/`。

## 5.5 下一步

- 入站过滤 → [六、message_scrub](./06-message-scrub.md)
- 测试 → [七、测试与文档](./07-tests-and-docs.md)
