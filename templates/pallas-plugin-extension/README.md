# Pallas-Bot 官方扩展包模板

复制为独立仓库 `pallas-plugin-<name>`，用于新建官方扩展（PyPI 分发）。  
本体 core（如 `llm_chat`、`pb_stats`）不走本模板。

## 怎么用

1. 复制本目录为新仓，全局替换 `TEMPLATE` / `pallas-plugin-TEMPLATE` / `pallas_plugin_TEMPLATE`
2. 按 [Golden Plugin](https://PallasBot.github.io/Pallas-Bot-Docs/developer/plugin-development/golden-plugin) 补齐 `PluginMetadata`、命令与配置
3. 业务只 `import pallas.api.*`（依赖 `pallas-core`，见本目录 `pyproject.toml`）
4. 用户向 README 从 [`readmes/`](readmes/) 选一份作底稿，改完放进扩展仓根目录
5. 发布见 [官方扩展发 PyPI](https://PallasBot.github.io/Pallas-Bot-Docs/developer/extension-pypi-publish)

## 用户如何安装（写进扩展仓 README）

```bash
# 推荐：控制台 → 插件商店 → 一键安装

# 或在 Pallas-Bot 根目录
uv run pallas ext install pallas-plugin-<name>

# 或
uv pip install pallas-plugin-<name>
```

开发联调：在扩展仓 `uv pip install -e .`，本体需已可用。

## 本目录内容

| 路径 | 说明 |
| --- | --- |
| `src/pallas_plugin_TEMPLATE/` | 最小插件骨架 |
| `pyproject.toml` | 包名、依赖、`pallas-core` 版本范围 |
| `readmes/` | 各官方扩展 README 底稿（手工拷到对应仓） |
| `.github/workflows/` | CI / PyPI 发布示例 |

更完整的插件约定见主仓 [AGENTS.md](../../AGENTS.md) 与文档站 [写插件](https://PallasBot.github.io/Pallas-Bot-Docs/developer/plugin-development/getting-started)。
