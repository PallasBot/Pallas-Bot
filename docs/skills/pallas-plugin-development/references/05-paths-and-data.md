# 五、路径、数据与资源

## 5.1 约定

| 类型 | 位置 | Helper |
| --- | --- | --- |
| 运行期数据 | `data/<plugin_name>/` | `plugin_data_dir("my_plugin")` |
| 静态资源 | `resource/<subdir>/` | `resource_dir("voices")` 等 |

```python
from src.foundation.paths import plugin_data_dir, resource_dir

DATA = plugin_data_dir("my_plugin")
VOICES = resource_dir("voices")
```

**不要**硬编码 `data/`、`resource/` 相对路径字符串；工作目录变化会导致漂移。

## 5.2 备份与排障

`data/<plugin_name>/` 按插件隔离，便于备份与按插件清理。大文件、缓存、下载物放数据目录；可复用静态素材放 `resource/`。

## 5.3 数据库

持久化优先走 `src.foundation.db` repository 模式；表结构与迁移遵循仓库现有插件（如 blacklist、request_handler）。新表需考虑 PostgreSQL 与 CI。

## 5.4 测试中的路径

测试可使用临时目录或 fixture；参考 `tests/plugins/` 下既有写法，避免写真实 `data/`。

## 5.5 下一步

- 入站过滤 → [六、message_scrub](./06-message-scrub.md)
- 测试 → [七、测试与文档](./07-tests-and-docs.md)
