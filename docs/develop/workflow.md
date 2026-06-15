# 贡献与提交流程

完整说明亦见仓库 [CONTRIBUTING.md](https://github.com/PallasBot/Pallas-Bot/blob/main/CONTRIBUTING.md) 与 [AGENTS.md](https://github.com/PallasBot/Pallas-Bot/blob/main/AGENTS.md)。

## Issue

提交前搜索是否已有同类问题：<https://github.com/PallasBot/Pallas-Bot/issues>

- **Bug**：现象、复现步骤、环境、脱敏日志
- **功能**：要解决的实际问题与期望行为
- **文档**：过时或缺失处可直接 PR

## 分支与 PR

- 从 `main` 拉功能分支，向 `main` 发起 PR
- **一个 PR 只解决一类问题**（功能 / 修复 / 文档 / 重构勿混杂）
- **最小必要改动**：避免无关格式化、大范围重排；历史问题在说明里标注「历史遗留」与「本次引入」

## 编码前必读

| 主题 | 文档 |
| --- | --- |
| 目录与分层 | [项目结构](../architecture/project-structure.md) |
| 插件组织 | [插件目录约定](../architecture/plugin-convention.md) |
| 命令权限 | [cmd_perm](../common/cmd_perm/README.md) |
| 配置落盘 | [配置存储](../architecture/settings-storage.md) |

## 提交前自检

```bash
uv run ruff check src/
uv run ruff format --check src/
uv run pytest   # 若改动涉及已有测试覆盖的行为
```

### 插件命令权限（cmd_perm）PR 清单

若新增或修改可走 cmd_perm 的命令：

- [ ] Matcher / 手动鉴权与 `extra["command_permissions"]`（或 `registry.DEFAULT_COMMAND_PERMISSIONS`）使用**同一命令 ID**
- [ ] `usage`、`menu_data.trigger_condition` **未写死**「群管/群主/仅管理员」等静态权限文案
- [ ] 已配置 `command_permission` / `command_permissions`，帮助图「何人可用」能反映当前等级
- [ ] 与权限无关的额外条件写在 `detail_des` 或 `docs/plugins/<name>/README.md`

### WebUI / 控制台页面

改动 **Pallas-Bot-WebUI** 或主仓内嵌控制台静态资源时，须在 **≤560px** 窄屏下自检布局。见 [WebUI 前端开发](webui.md)。

## Commit 信息

推荐格式（与仓库日常习惯一致）：

```text
feat(scope): 简要中文说明
fix(scope): …
docs(scope): …
refactor(scope): …
chore(scope): …
```

- 一个 commit 聚焦一件事
- **勿提交** `config/pallas.toml`、`data/`、`webui.json`、token 等私密内容

## 文档改动

- 用户向插件说明：`docs/plugins/<name>/README.md`（可复制 [TEMPLATE.md](../plugins/TEMPLATE.md)）
- 架构与开发约定：`docs/architecture/`、`docs/develop/`
- 在线站由 CI 将主仓 `docs/` 同步至 [Pallas-Bot-Docs](https://github.com/PallasBot/Pallas-Bot-Docs)（见 [docs/README.md](../README.md#同步-web-文档)）

本地预览同步结果：

```bash
uv run python tools/scripts/sync_docs_to_web.py
# 在 Pallas-Bot-Docs 目录执行 npm run dev
```

## 沟通

可在 Issue 留言或加入 README 中的 QQ 开发者群。
