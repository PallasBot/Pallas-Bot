# 官方插件与 pallas-core PyPI 发版

扩展包以 `pallas-plugin-*` 发 PyPI；内核 SDK 为 `pallas-core`（版本取自 `pallas/__init__.py` 的 `__version__`）。

## pallas-core（主仓）

| 项 | 说明 |
| --- | --- |
| 构建 | `./scripts/build_core.sh` |
| CI | `.github/workflows/publish-pypi-core.yml` |
| 触发 | push tag **`v*`**（须与 `pallas.__version__` 一致，如 `v4.0.0`） |
| Trusted Publisher | PyPI 项目 `pallas-core` → 仓库 `Pallas-Bot` → workflow `publish-pypi-core.yml` |

本地自检：

```bash
./scripts/build_core.sh
unzip -l build/pallas-core/dist/*.whl | grep 'pallas/__init__'
```

发版：合并到 `main` / 发版分支后打 tag 并 push，例如 `git tag v4.0.0 && git push origin v4.0.0`。

## 官方插件（独立仓）

## 一次性：PyPI Trusted Publisher

对每个扩展 GitHub 仓库，在 [pypi.org](https://pypi.org) 对应项目中添加 Trusted Publisher：

| 字段 | 值 |
| --- | --- |
| Owner | `TogetsuDo`（或实际 org） |
| Repository | `pallas-plugin-<name>` |
| Workflow | `publish-pypi.yml` |
| Environment | `pypi`（可选，与 workflow 一致） |

GitHub 仓库 Settings → Environments → 新建 **`pypi`**（workflow 引用该 environment）。

## 发版步骤

1. 合并 hatch / 代码变更到 `main`
2.  bump `pyproject.toml` 的 `version`（semver，与主仓 4.x 对齐）
3. 打 tag **`v<version>`**（须与 `pyproject.toml` 一致，如 `v4.0.1`）
4. push tag → Actions **`Publish PyPI`** 构建 wheel、校验含 `__init__.py` 后上传

本地自检：

```bash
uv build
unzip -l dist/*.whl | grep __init__
```

## 主仓联动

1. `pyproject.toml` extras：`pallas-plugin-*>=4.0.1,<5.0.0`，**无** `[tool.uv.sources]` git 覆盖
2. **PyPI 首包全部可用后** 在主仓执行：

```bash
uv lock
uv sync --dev --extra coord-redis   # 与 CI 一致
git add uv.lock && git commit -m "chore(deps): 官方插件改 PyPI 锁定"
```

3. 本地联调扩展仓改动时，可**临时**加 `[tool.uv.sources]` path/git，**勿提交**

::: warning 顺序
先完成 **7 仓 push + v4.0.1 tag + PyPI 发版**，再合入主仓 `pyproject` / `uv.lock` 变更；否则 `uv lock` 会因 PyPI 无包而失败。
:::

## 升级用户说明

3.x → 4.0 站点若已有 **`local/plugins/`** 副本，**不必**因 PyPI 上线而重装；pip 仅在一键安装 / 统一 venv 时需要。
