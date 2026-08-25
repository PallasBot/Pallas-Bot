---
name: pallas-release
description: >
  当维护者说「发版」「release」「更新公告」「错开发版」「要发 Bot/WebUI 了」时，优先读取本 SKILL。
  处理 Pallas-Bot 主仓与 Pallas-Bot-WebUI 的发版（更新公告、chore(release)、dev→main PR、Auto Tag Release 与 Release 工作流出包）。
  本 SKILL 是发版流程的唯一权威来源；旧 ~/.cursor/rules/pallas-release.mdc 已精简为指针。
---

# Pallas 发版（Agent 入口）

> 本 Skill 描述 Pallas-Bot 与 Pallas-Bot-WebUI 的发版流程。维护者说「发版 / release」时读取并遵守。
> 本文是发版流程的**权威来源**；历史规则 `~/.cursor/rules/pallas-release.mdc` 仅留指针，**不再双源维护**。
> 人类维护者的发布说明见 [pallas-release](https://github.com/PallasBot/Pallas-Bot-Docs)（如有）。

## 何时触发

- 维护者说「发版准备」「release」「错开发版」「Bot/WebUI 该发了」。
- 默认 **patch**；WebUI 要 minor/major 时给合入 `main` 的 PR 打 `bump:minor` / `bump:major`。

## 发版前必读：摸清本版内容（决定公告质量）

发版前**先完整梳理本版带了什么**，再动笔写公告：

1. **本版功能/修复**：`git log origin/main..dev --oneline`（Bot/WebUI 各自仓内跑），逐条看有没有 `feat` / `fix` / 行为变化；feature 分支已合入哪些。
2. **新配置项**（写公告必须点名，尤其面向用户的开关）：
   - 新增环境变量：搜 `os.getenv(`、`env_`、`REDIS_URL` 等模式，或对照 `config/pallas.example.toml` 与 `docs/`；
   - 新增 WebUI 可调项 / config 段：搜 `install_hot_reload_config`、`env_sections.py`、`webui.json` 相关；
   - 新默认值/行为变化（如开关默认关闭、限额默认值）要写清楚开启方式。
3. **CHANGELOG 里的「提前备忘」**：维护者可能提前在 `Unreleased` / 顶部写入备忘说明（新配置、新功能、已知限制），这些是**要整理进更新公告**的材料，不是重复的内部 commit 明细。
4. **两端配套**：Bot 是否捆绑 WebUI（`dist.zip`）；本轮 WebUI 是否一并发版；WebUI 契约是否有变化（决定「需要 Bot ≥ …」写法）。
5. **错开发版**：若维护者要求 Bot 与 WebUI 错开/间隔发版，各自按本流程单独走，版本各自独立，互不绑定。

## 分支与合入顺序

- 发版 PR：`dev` → `main`。
- **先合 WebUI 并出 tag，再合 Bot**；Bot Release 从 WebUI `main` 最新 `v*` 捆绑 `dist.zip`。
- **WebUI**：合入 `main` 后由 Release **自动**递增版本并打 `v*` tag（`release.yml` 监听 **PR merged 到 main** 或 push `v*` tag / `workflow_dispatch` 触发；PR 合入时默认 patch 递增 `package.json` 并打 tag）。WebUI 的 `chore(release)` 提交本身不触发打 tag，由 Release 工作流在合并后处理。
- **Bot**：合入 `main` 后由 **Auto Tag Release** 工作流（`auto-tag-release.yml`）检测 **push 到 main 的 HEAD 提交**是否为 `chore(release): vX.Y.Z`（squash 合入时 HEAD 即发版提交；merge commit 时取 HEAD^2=dev tip；main 直发 HEAD 即发版提交同样命中），命中即自动打 `vX.Y.Z` tag 并触发 `Release`（出 GitHub Release / 捆绑 `dist.zip` / Docker）与 **`publish-pypi-core`**（发布 `pallas-core` 到 PyPI）。未命中（HEAD 非发版提交、或 tag 已存在）则跳过；需要补发时对 `Release` 工作流 `workflow_dispatch`，传入 `version=vX.Y.Z`（可选 `webui_tag=v…`），PyPI 则对 `publish-pypi-core` `workflow_dispatch`。勿空等 auto-tag。
- 开 Bot 发版 PR 前：本地 `dev` **先快进 / 对齐** `origin/main`（避免 `dev` 落后于 `main` 的纯文档/合入提交漏在 PR 外或把无关 diff 搅进来），再叠本版功能与发版提交。
- 本版尚未合入 `dev` 的功能（如 feature 分支）：先合入 / cherry-pick 到 `dev`，再做发版提交。

## `dev` 上的提交形态（必守）

发版准备完成后，`origin/main..dev` 应满足：

1. **最多一条** `chore(release): vX.Y.Z`。
2. 该发版提交必须是 **`dev` 的 tip（最顶提交）**；其下可以是本版功能 / 修复 commit。
3. **禁止**在 `chore(release)` 之后再堆 `fix` / `feat` 把发版顶掉。若 review / CI 修正在发版提交之后落地：把修正 **squash / 重排进发版之前的功能提交**，再重提 **一条** tip 为 `chore(release)`，必要时对 `dev` `--force-with-lease`（**禁止**强推 `main`）。
4. 出现多条 `chore(release)`，或 tip 不是发版提交：soft-reset / 重排后重提，维护者要求时可对 `dev` `--force-with-lease`。

推荐拆分：

| 提交 | 内容 |
| --- | --- |
| `feat` / `fix` … | 本版代码与测试；**不要**改版本号与本版 CHANGELOG 段 |
| tip：`chore(release): vX.Y.Z` | **仅**版本号 + 本版 CHANGELOG（Bot：`pyproject.toml`、`pallas/__init__.py`、`CHANGELOG.md`） |

## 提交与 PR

| 项 | 约定 |
| --- | --- |
| Commit | `chore(release): vX.Y.Z`（Bot / WebUI 相同） |
| PR 标题 | 与发版 commit 标题相同 |
| PR 正文 | 只写本版变更；不写打 tag、合入顺序、CI、强推等流程说明 |
| 合入方式 | **用 merge commit（no-ff）**，保留完整 feature 历史；squash 会压成单条、丢失提交历史。Auto Tag Release / Release 对两种合入方式都兼容 |
| dev 同步 | 合入后 `dev` 对齐 `main`（fast-forward）；若用 no-ff 合入，`dev` 落后于 `main` 一个 merge commit，直接 reset 到 `origin/main` 即可 |

## CHANGELOG

两端本版都写 **`### 更新公告`**，文风按面向用户的更新说明来写（直接、可读，少空话与内部黑话）：

- **一行一点**：用无序列表书写，每条说清一件事；可写得比 Added/Fixed 更面向使用场景，但避免内部黑话。
- 不用「你会明显感觉到」一类固定小节，也不写成一大段逗号串联。
- 不写发版操作句（例如须先发 WebUI tag、须强推 `dev`）。
- 可用 `### Added` / `### Fixed` / `### Changed` 作面向开发者的明细；Bot 捆绑控制台时在公告里单列一点写清 WebUI 版本。
- CHANGELOG 顶部保持简洁：写标题与（可选）Releases 链接即可，**不要**写「遵循 Keep a Changelog / 语义化版本」一类套话。
- **公告材料来源**：优先用 CHANGELOG 里维护者提前写的备忘说明 + 发版前梳理出的新功能/配置项；用面向用户的话重组，别照抄 commit 明细。

### Bot 公告格式（按功能分类 + 二级列表）

公告按**功能分类**组织，**同一功能的多个点用二级列表**；不要同一分类标签反复并列独立条目，也不要把功能点硬塞成一条长句。

```markdown
### 更新公告

- **功能分类**：
  - 该功能的一个变化点，简洁一句
  - 同一功能的另一个变化点
- **另一分类**：
  - 一个变化点
- 捆绑控制台 WebUI v0.9.x（Bot 捆绑控制台时单列一条）
```

- 每条公告简洁，**不写环境变量名、默认值、预算数值**（配置项点名留给 `### Added` / docs）。
- 条目不用句号结尾（与 4.3.x 既有风格一致）。
- `### Added` / `### Fixed` / `### Changed` 作面向开发者明细：每条 `* type(scope): 描述` **独立一行**、不换行拼接；可按需排序归组。

### WebUI 须写最低 Bot 版本

WebUI 更新公告**第一条（或靠前）**须写明本版控制台依赖的 **最低 Bot 版本**（如「需要 Bot ≥ x.y.z；请勿只升控制台」）。版本取本轮一并发布（或已发布）的 Bot 版本；无后端契约变化时可写「仍需 Bot ≥ …」。**Bot 自己的 CHANGELOG 不必写「需要 Bot ≥ …」。**

## WebUI

1. 在 `CHANGELOG.md` 的 `<!-- entries -->` 下写 `## [Unreleased]`，正文按更新公告写（**含最低 Bot 版本**；可先有功能 commit，再补公告 / 发版 commit）。
2. 提交 `chore(release): vX.Y.Z` 且为 **`dev` tip**（预期合入后版本；**不要**手改 `package.json` version，由合入 `main` 的 Release 递增并打 tag）。
3. 开 PR：`--base main --head dev`，标题=发版 commit，正文=变更。
4. PR 合并后由 Release 工作流自动递增 `package.json` 并打 `vX.Y.Z` tag、出 GitHub Release 资产。确认出现 tag 与资产后再收尾（同步 `dev`←`main`、清分支）。未自动触发时 `workflow_dispatch` 传 `bump=patch`。

## Bot

1. 对齐 `origin/main` → 合入本版功能 → 再发版。
2. 同步 `pyproject.toml` 与 `pallas/__init__.py` 版本号（**只在** `chore(release)` 里改）。
3. `CHANGELOG.md` 顶部写本版正式段（含更新公告；Bot 直接写 `## [X.Y.Z]`，不走 Unreleased）。
4. 提交 `chore(release): vX.Y.Z`（版本文件 + CHANGELOG 同 commit），并确保其为 **`dev` tip**。
5. 开 PR：标题=发版 commit，正文=变更。
6. `main` 合入后由 Auto Tag Release 自动打 tag 并触发 `Release` 与 `publish-pypi-core`（确认出现 `vX.Y.Z` tag、Release 资产与 PyPI 发布后再收尾：同步 `dev`←`main`、清分支）。若本次 push 未命中发版提交而未自动触发，手动打 tag 或 `workflow_dispatch`。

## Bot 在 `main` 直接发版

维护者指定 bot 直接在 `main` 发版（不走 `dev`→`main` PR，如功能直接落在 `main`）时：

1. 改版本号与 CHANGELOG（仍是发版文件），**amend 进 `main` 最新提交**，保持单提交形态。
2. `git push origin main`：最新提交未推送时 amend 无需强推；若已推送，须维护者授权后才 `--force-with-lease`。
3. **推送后 Auto Tag Release 自动打 tag**（`auto-tag-release.yml` 检测 push 到 `main` 的 HEAD 提交是否为 `chore(release): vX.Y.Z`；main 直发若 HEAD 是发版提交同样命中，无需手动）。若 HEAD 不是发版提交（如 amend 未成功或 push 的是普通提交），**手动打签名 annotated tag** `vX.Y.Z` 并确认 `Release` 工作流出包。
4. 打 tag 后确认 `Release` 工作流出包（并确认 `publish-pypi-core` 发布到 PyPI）；WebUI 仍按标准流程先发并出 tag，再发 Bot。

## 错开发版

维护者要求 Bot 与 WebUI 错开 / 间隔发版时：

- **各自独立**走本流程：版本号各自计算、各自 `chore(release)`、各自 PR 与 tag；不要求同一轮。
- 先发的一方按正常流程收尾（合并、出 tag、Release 就绪）；后发的一方在发起前**对齐已发布的 `main`** 再叠发版提交。
- WebUI 的「需要 Bot ≥ …」仍以**已发布**的 Bot 版本为准；若 Bot 尚未发但将先于 WebUI 发布，写预期版本并注明发布顺序。
- 更新公告里两端各自单列，不混写。

## Agent

- 先给 CHANGELOG、版本、PR 标题与正文草案，确认后再提交 / 开 PR / `--force-with-lease`。
- 开 PR 后跟 CI 与有效 review；若修正导致 tip 不再是 `chore(release)`，按上文重排后再推（需维护者已授权发版 / 强推 `dev` 时可用 `--force-with-lease`）。
- Bot 发版 PR 合并后确认 Auto Tag Release 已打 tag、`Release` 就绪、`publish-pypi-core` 已发布 PyPI；若自动触发未生效，再手动 `gh release create` / `gh workflow run Release`（或等价打 tag）并等到 Release 就绪。
- 不擅自强推 `main`；不默认登记 Notion。

## 流程文件维护

- 本 SKILL（`docs/skills/pallas-release/SKILL.md`）是权威来源；改流程时**先改这里**。
- 同步副本在 `~/.config/opencode/skills/pallas-release/`（opencode 加载用），改动后需同步。
- `~/.cursor/rules/pallas-release.mdc` 只留指针，不再维护双份。
