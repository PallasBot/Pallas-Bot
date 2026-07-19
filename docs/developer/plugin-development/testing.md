# 测试

覆盖行为、元数据、配置与分片相关路径；目录与最小例见下。

## 覆盖矩阵

| 层 | MUST 覆盖 | 目录 |
| --- | --- | --- |
| 行为 | 主命令 / 触发 / 关键输出 | `tests/plugins/<name>/` |
| 元数据 | `command_permissions`、`menu_data`、`command_limits`、ID 一致、`reload_policy` | 同上 |
| 配置 | 默认值、开关对行为的影响 | 同上 |
| 分片 | 独占、claim、hosted activity、callback（若涉及） | `tests/plugins/` 或 `tests/platform/` |

平台横切：`tests/common/`、`tests/platform/`。

## 元数据最小例

```python
from packages.blacklist import __plugin_meta__


def test_blacklist_metadata_uses_sdk_declarations():
    perms = __plugin_meta__.extra.get("command_permissions") or []
    assert len(perms) == 3
    assert __plugin_meta__.extra.get("reload_policy") == "metadata"
```

对照仓库内 `tests/plugins/*/test_*_metadata.py`。

## 不足的信号

| 仅有 | 缺少 |
| --- | --- |
| 「函数可调用」 | 权限 / metadata 是否被平台理解 |
| 单进程冒烟 | 分片下去重与独占 |
| 无配置断言 | 热载语义与默认值 |

## 本地命令

```bash
uv run pytest tests/plugins/<name>/ -q
uv run ruff check pallas/ packages/
```

流程：[environment](../../develop/environment.md)、[workflow](../../develop/workflow.md)。

## 相关

- [Golden Plugin](golden-plugin.md)
- [元数据](metadata.md)
