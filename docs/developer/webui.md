# WebUI 前端开发

控制台 UI 由独立仓库 **[Pallas-Bot-WebUI](https://github.com/PallasBot/Pallas-Bot-WebUI)** 构建，产物由主仓 `pb_webui` 挂载，基址 **`/pallas/`**。

后端 API 见 [WebUI API](/common/webui/api/)（实现主要在 `packages/pb_webui`）；插件配置热重载见 [WebUI 配置与热重载](/common/webui)。

## 本地联调

```bash
# 终端 1：主仓 Bot
cd Pallas-Bot
uv run pallas

# 终端 2：WebUI 开发服务器
cd Pallas-Bot-WebUI
npm install
npm run dev    # 默认 http://127.0.0.1:5173/pallas/
```

`npm run dev` 将 `/pallas/api`、`/pallas/plugin-assets`、`/pallas/store-assets` 等代理到 `http://127.0.0.1:8088`。后端端口非 8088 时：

```bash
VITE_PROXY_TARGET=http://127.0.0.1:<port> npm run dev
```

## 构建与挂载

```bash
cd Pallas-Bot-WebUI
npm run build   # vue-tsc + vite build
```

主仓 CI / Release 会从 **Pallas-Bot-WebUI** checkout 源码，经 `tools/build_webui_dist.sh` 构建并打包 **`dist.zip`**（zip 根为 `public/`），随 **Pallas-Bot Release** 附件发布。Bot 启动时解压到 **`data/pb_webui`**，静态目录为 **`data/pb_webui/public`**（与 `webui_public_path()` 一致）。

本地手动部署：将构建产物放入 `data/pb_webui/public/`，或解压 Release 的 `dist.zip` 到 `data/pb_webui/`。

```bash
# 主仓内一键构建 zip（需已 clone WebUI 到 ../Pallas-Bot-WebUI 等路径）
./tools/build_webui_dist.sh /path/to/Pallas-Bot-WebUI dist.zip
unzip -d data/pb_webui dist.zip
```

自动更新默认从 **`PallasBot/Pallas-Bot`** Release 下载 `dist.zip`（配置项 `pallas_webui_dist_zip_repo`）。

## OpenAPI 契约

控制台后端可在线提供：

```text
/pallas/api/openapi.json
```

如需离线导出给前端 codegen 或评审：

```bash
cd Pallas-Bot
uv run python tools/export_pb_webui_openapi.py
```

默认输出到：

```text
openspec/pallas-console-v1.json
```

双仓同步与 drift 门禁：

```bash
# Bot：导出并提交 openspec
cd Pallas-Bot
uv run python tools/export_pb_webui_openapi.py
uv run python tools/check_console_openapi_drift.py

# WebUI：从主仓 openspec 生成类型并校验
cd Pallas-Bot-WebUI
npm run gen:console-openapi-types
npm run check:console-openapi-types
```

CI 分别在两仓执行上述 check。

### DynamicConfigPanel（插件 config 元数据）

插件 `config.py` 的 Pydantic 字段可通过 `Field(..., json_schema_extra={...})` 驱动 WebUI 表单：

| 键 | 作用 |
| --- | --- |
| `ui_group` | 分组标题（DynamicConfigPanel 折叠卡片） |
| `ui_order` | 组内排序，越小越靠前 |
| `ui_hidden` | 进阶项，默认折叠在「高级」组 |
| `secret` | 字符串打码 + 眼睛切换 |
| `multiline` | 多行 textarea |

未在 schema 声明但写入 `webui.json` 的键会在面板底部「未声明的环境键」列出；需改 Raw TOML 模式编辑。

## 代码约定

| 项 | 约定 |
| --- | --- |
| 技术栈 | Vue 3、TypeScript、Vite、Vue Router、Axios |
| 主要目录 | `src/pages/` 页面、`src/styles/app.css` 全局样式 |
| 样式 | 优先复用 `panel`、`panel__hd--split`、`row-actions`、`inst-db-panel__hd` 等已有类 |
| 页面特有样式 | Vue `scoped` 或 `app.css` 中带页面根类名前缀 |
| 函数命名 | 非必要不以 `_` 开头；注释保持精简 |

仓库根 [AGENTS.md](https://github.com/PallasBot/Pallas-Bot-WebUI/blob/main/AGENTS.md) 与主仓 AGENTS.md 中 WebUI 章节保持一致。

## 窄屏体验（必做）

大量用户在手机或窄窗口使用控制台。**新增或改动标题栏、表格、批量操作、侧栏按钮时，必须在 ≤560px 下可用。**

自检断点：`src/styles/app.css` 中 `@media (max-width: 560px)`。

| 场景 | 做法 |
| --- | --- |
| 面板标题 +「添加到侧栏」 | 宽屏 `panel__hd--split`；窄屏标题与 `+` 同一行右上，批量按钮次行 |
| 实例/协议双行标题 | `inst-db-panel__hd` 系列；窄屏 grid 见 `app.css` |
| 多列表格 | `table-wrap` 横向滚动；列多或长路径时窄屏用**卡片列表**（参考 `DatabaseBackupsPage.vue`） |
| 全局按钮全宽规则 | 勿误伤标题栏内按钮；参考 `friends-groups-req-hd-bulk-btns` 等 override |

参考页面：`FriendsGroupsPage.vue`、`DatabaseBackupsPage.vue`、`InstancesPage.vue`、`ProtocolManagePage.vue`。

提交前用 DevTools 响应式模式或真机预览 **≤560px** 宽度，勿只验桌面宽屏。

## 与主仓协作

| 改动类型 | 仓库 |
| --- | --- |
| 新页面、样式、前端交互 | Pallas-Bot-WebUI |
| 新 API、权限、配置落盘 | Pallas-Bot（`pallas_webui` / `common/webui`） |
| 内嵌协议端静态页 | 主仓 `src/plugins/pb_protocol/web/static/`（同样遵守窄屏） |

PR 仍建议**单一主题**：前后端分拆为两个 PR 时，在描述中互相链接。

## 插件包内视觉资源

插件列表、商店本地插件与帮助图共用后端 `resolve_catalog_visuals()`。在 `local/plugins/<id>/` 或 `packages/<id>/` 放置 `assets/cover.png`、`assets/icon.png` 等（完整候选见 [Golden Plugin · 包内视觉资源](/developer/plugin-development/golden-plugin#包内视觉资源assets)）后：

- API 字段 `cover` / `icon` / `avatar` 按 **包内 → 商店缓存 → 远程** 合并后返回 `/pallas/plugin-assets/…` 或 `/pallas/store-assets/…`
- 前端 `resolvePluginIconForRow()` **优先**使用上述 API 字段，再回退商店远程 URL 或品牌 mascot
- bundled README 中相对路径 `assets/…` 会改写为同前缀 URL（`normalizeBundledReadmeMarkdown`）

## 提交

```bash
npm run build   # 提交前确保通过
```

Commit 推荐：`feat(webui): 中文说明` / `fix(webui): …`

## 延伸阅读

- [贡献与提交流程](workflow.md)
- [WebUI 插件配置（后端）](/common/webui)
- [本地开发环境](environment.md)
