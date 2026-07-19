# 写社区插件并上架

本页面向**插件作者**：把仓库整理成商店可识别的形态，自检通过后向索引仓提 PR。用户安装方式见 [社区插件商店](community-plugin-store.md)；代码结构合同见 [Golden Plugin](/developer/plugin-development/golden-plugin)。

## 你要完成什么

| 阶段 | 产出 |
| --- | --- |
| 开发 | 符合 NoneBot 包结构的独立仓库 |
| 自检 | `community_plugin_author.py check` 通过（可选 L2 画像） |
| 收录 | 向 [community-plugin-index](https://github.com/PallasBot/community-plugin-index) 追加 `index.json` 条目并提 PR |

---

## 三种接入方式（落点相同）

| 方式 | 适用 | 做法 |
| --- | --- | --- |
| **索引收录** | 希望公开展示、被商店发现 | 向 community-plugin-index 提 PR |
| **Git 直装** | 运维自行安装，不进公共索引 | WebUI **插件商店 → 社区插件 → 从 Git 安装** |
| **手工投放** | 内网或本地调试 | 复制目录到 `local/plugins/<id>/` |

同名冲突时 **`local/plugins` 优先于官方插件**。

---

## 步骤 1：整理插件目录

最小结构（与 NoneBot 一致）：

```text
my_plugin/
├── __init__.py          # 含 __plugin_meta__（PluginMetadata）
├── README.md            # 商店详情页会尝试展示
└── assets/
    └── icon.png         # 推荐 256×256，商店卡片图标
```

约定：

| 项 | 规则 |
| --- | --- |
| 插件 ID | 小写字母开头，仅 `a-z` / `0-9` / `_`，最长 64；与 `local/plugins/<id>/` 目录名一致 |
| `PLUGIN_ID` | 可在 `__init__.py` 定义，便于与目录名对齐 |
| 最低版本 | 依赖 Pallas-Bot 内核时在 README 注明（如 **4.0.0**） |
| 权限 | 接入 [cmd_perm](/common/cmd_perm) 的 `command_permissions` 后，帮助图自动展示「何人可用」 |

---

## 步骤 2：维护版本与更新日志

1. **版本号**：遵循[语义化版本](https://semver.org/lang/zh-CN/)（如 `0.1.0`）。`index.json` 可选字段 `version` 应与 git tag、`CHANGELOG.md` 对应。
2. **git tag**：发布时打 `vX.Y.Z`（如 `v0.1.0`），便于按 ref 安装。
3. **`CHANGELOG.md`**：仓库根目录维护，推荐 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)：日常记到 `## [Unreleased]`，发布时按版本归档。

控制台 **插件商店 → 详情 → 更新日志** 取值顺序：

1. 仓库根目录 `CHANGELOG.md`（首选）
2. 缺失时，对已装到 `local/plugins/<id>/` 的副本按本地 git 提交标题兜底生成

::: tip
建议维护 `CHANGELOG.md`。缺失时用户只能看到原始提交记录；README 中可写当前版本号（如「当前版本：v0.1.0」），勿依赖徽章组件。
:::

示范仓库：[`pallas-community-plugin-interact`](https://github.com/TogetsuDo/pallas-community-plugin-interact)。

### 社区插件画像（L1 / L2）

公开收录与 WebUI「指令与能力」看 **metadata 完整度**：

| 档位 | 要点 |
| --- | --- |
| **L1（索引默认门槛）** | `command_permissions` + `menu_data` + 规范 `usage` |
| **L2（优选）** | L1 + `command_limits` + 鉴权 ID 一致；命令推荐 `plugin_sdk` |

`check --profile L1|L2` 校验 metadata 与命令 ID 一致性；目录、图标、README 仍是基础结构检查。

---

## 步骤 3：准备图标与索引元数据

商店卡片与插件列表视觉资源优先级（`resolve_catalog_visuals()`）：

1. 已安装插件包内 `assets/`（`/pallas/plugin-assets/<plugin_id>/…`）
2. 商店资源快照缓存（`/pallas/store-assets/…`）
3. 索引 / 官方插件条目中的 `cover`、`icon`、`avatar`（完整 URL）
4. 自动推断远程：`https://raw.githubusercontent.com/<owner>/<repo>/<ref>/assets/icon.png`（Gitee 同理）
5. 作者 GitHub 头像（`author` 或仓库 owner）

**推荐**：仓库放 `assets/icon.png`（可选 `cover.webp`、`avatar.png`），索引只写 `repository`；装到 `local/plugins` 后控制台直接读包内文件。

包内路径规则：[Golden Plugin · 包内视觉资源](/developer/plugin-development/golden-plugin#包内视觉资源assets)。

索引单条示例（追加到 `index.json` 的 `plugins`）：

```json
{
  "id": "my_plugin",
  "name": "我的插件",
  "description": "一句话说明功能。",
  "repository": "https://github.com/you/my_plugin.git",
  "ref": "main",
  "version": "0.1.0",
  "author": "your_github_id",
  "tags": ["工具"],
  "min_pallas_version": "4.0.0"
}
```

提 PR 前更新根级 **`updated_at`**（ISO 日期），便于客户端刷新图标缓存。

---

## 步骤 4：用作者工具 CLI 自检

在 **Pallas-Bot 仓库根目录**执行。

### 校验插件目录

```bash
uv run python tools/community_plugin_author.py check path/to/my_plugin
uv run python tools/community_plugin_author.py check path/to/my_plugin --profile L2
```

检查 `__init__.py`、ID 规范、推荐 `assets/icon.png` 与 README，并输出画像摘要 JSON。

### 生成索引条目

从插件目录读 `PluginMetadata` 草稿：

```bash
uv run python tools/community_plugin_author.py index-entry ./my_plugin \
  --repository https://github.com/you/my_plugin.git \
  --author your_github_id \
  --tags "工具,示例"
```

无本地目录时也可只按仓库生成：

```bash
uv run python tools/community_plugin_author.py index-entry \
  --repository https://github.com/you/my_plugin.git \
  --id my_plugin \
  --name "我的插件" \
  --description "简介"
```

把 stdout 里的 JSON 追加到 community-plugin-index 的 `index.json`。

### README 插件列表（索引仓 CI 自动）

**不用手改 README 表格。** 索引仓 CI 在 PR / push `main` 时跑 `tools/sync_readme.py`，更新 `<!-- PLUGIN_LIST_START -->` … `<!-- PLUGIN_LIST_END -->`。

本地预览（在 community-plugin-index 仓库根目录）：

```bash
python tools/sync_readme.py --write
python tools/sync_readme.py --check
```

### 校验 index.json

```bash
uv run python tools/community_plugin_author.py validate-index
# 或指定路径
uv run python tools/community_plugin_author.py validate-index /path/to/index.json
```

索引仓另有 `python tools/validate_index.py`（与 CI 一致）。

---

## 步骤 5：提交收录 PR

合并前对照：

- [ ] 开源仓库，HTTPS clone 可访问（GitHub / Gitee / GitLab / Codeberg）
- [ ] 插件 ID 全局唯一，符合命名规范
- [ ] 仓库根即为 NoneBot 插件包（含 `__init__.py`），或 README 说明 clone 后路径
- [ ] `assets/icon.png` 或索引中提供 `icon`
- [ ] `description` 一句说清功能；`min_pallas_version` 如实填写
- [ ] 建议维护 `CHANGELOG.md`（Keep a Changelog），发布打 `vX.Y.Z` tag，条目可填 `version`
- [ ] 更新 `index.json` 的 `updated_at`

合并后 CI 同步 README 插件列表；Bot 拉远程 `index.json` 即可在商店展示。

---

## 私有 / 公会索引

站点可在 `config/pallas.toml` 用自建索引，不必进公共策展仓：

```toml
[env]
COMMUNITY_PLUGIN_INDEX_URL = "https://example.com/my-guild-index.json"
```

或落盘 `data/pallas_config/community_plugin_index.json` 覆盖远程。

---

## 相关

| 项 | 位置 |
| --- | --- |
| 商店使用 | [community-plugin-store.md](community-plugin-store.md) |
| 站点 `local/plugins` | [站点定制](/maintainer/deploy/upgrade) |
| 索引加载 | `src/console/webui/community_plugin_index.py` |
| Git 安装 | `src/console/webui/community_plugin_install.py` |
| 作者工具 | `tools/community_plugin_author.py` |
