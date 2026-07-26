# 五、路径、数据与资源

权威页：[Golden Plugin · 存储与路径](../../../developer/plugin-development/golden-plugin.md)、[config-and-webui](../../../developer/plugin-development/config-and-webui.md)。

## 5.1 约定

| 类型 | 位置 | Helper |
| --- | --- | --- |
| 群/用户/牛/部署级结构化状态 | DB `plugin_storage` | `GroupPluginStorage` + `extra["plugin_storage"]` |
| 大文件、缓存、导出 | `data/<plugin_name>/` | `plugin_data_dir("my_plugin")` |
| 静态资源 | `resource/<subdir>/` | `resource_dir("voices")` |

```python
from pallas.api.storage import GroupPluginStorage
from pallas.api.paths import plugin_data_dir, resource_dir

store = GroupPluginStorage("my_plugin", group_id)
CACHE = plugin_data_dir("my_plugin")
VOICES = resource_dir("voices")
```

**不要**硬编码 `data/`、`resource/` 相对路径字符串。

## 5.2 何时用哪种

| 场景 | 推荐 |
| --- | --- |
| 群开关、计数、小 JSON | `plugin_storage` |
| 图片/语音、日志、导出 | `plugin_data_dir` |
| 只读素材 | `resource_dir` |
| 跨群关系、审计、复杂查询 | `pallas.core.foundation.db` repository（内置插件） |

## 5.3 测试

临时目录 / fixture；参考 `tests/plugins/`，避免写真实 `data/`。见 [七](./07-tests-and-docs.md)。

## 5.4 下一步

- 入站过滤 → [六、message_scrub](./06-message-scrub.md)
- 测试 → [七、测试与文档](./07-tests-and-docs.md)
