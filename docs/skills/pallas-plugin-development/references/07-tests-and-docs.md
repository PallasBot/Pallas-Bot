# 七、测试与文档

## 7.1 测试

- 目录：`tests/plugins/<plugin_name>/`，尽量镜像 `src/plugins/<plugin_name>/`
- 运行：`uv run pytest tests/plugins/my_plugin/`
- 至少覆盖：配置解析、核心纯函数、权限/规则边界（可参考 `tests/plugins/blacklist/`、`tests/plugins/repeater/`）

提交前：

```bash
uv run ruff check src/
uv run ruff format --check src/
```

## 7.2 用户向文档

- `docs/plugins/<name>/README.md`（可复制 [TEMPLATE.md](../../plugins/TEMPLATE.md)）
- 在 [plugins/README.md](../../plugins/README.md) 索引登记
- 表格可列代码默认命令等级，注明以 WebUI 为准

## 7.3 Agent / 贡献者

- 协作约定：[AGENTS.md](../../../AGENTS.md)、[CONTRIBUTING.md](../../../CONTRIBUTING.md)
- 提交流程：[develop/workflow.md](../../develop/workflow.md)

## 7.4 完整插件 checklist

见 [八、golden plugin checklist](./08-golden-plugin-checklist.md)
