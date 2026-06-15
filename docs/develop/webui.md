# WebUI 前端开发

控制台 UI 由独立仓库 **[Pallas-Bot-WebUI](https://github.com/PallasBot/Pallas-Bot-WebUI)** 构建，产物由主仓 `pallas_webui` 插件挂载，基址 **`/pallas/`**。

后端 API 实现在主仓 `src/plugins/pallas_webui/`（如 `extended_api.py`）；**插件配置热重载**等通用能力在 `src/common/webui/`，一般无需改 API 层即可接入新插件配置（见 [WebUI 插件配置](../common/webui/README.md)）。

## 本地联调

```bash
# 终端 1：主仓 Bot
cd Pallas-Bot
uv run nb run

# 终端 2：WebUI 开发服务器
cd Pallas-Bot-WebUI
npm install
npm run dev    # 默认 http://127.0.0.1:5173/pallas/
```

`npm run dev` 将 `/pallas/api` 代理到 `http://127.0.0.1:8088`。后端端口非 8088 时：

```bash
VITE_PROXY_TARGET=http://127.0.0.1:<port> npm run dev
```

## 构建与挂载

```bash
cd Pallas-Bot-WebUI
npm run build   # vue-tsc + vite build
```

将 `dist/` 内容按主仓 `pallas_webui` 约定复制或 CI 发布到主仓静态资源目录。生产环境通常直接使用主仓内置构建结果，无需单独起 Vite。

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
| 内嵌协议端静态页 | 主仓 `src/plugins/pallas_protocol/web/static/`（同样遵守窄屏） |

PR 仍建议**单一主题**：前后端分拆为两个 PR 时，在描述中互相链接。

## 提交

```bash
npm run build   # 提交前确保通过
```

Commit 推荐：`feat(webui): 中文说明` / `fix(webui): …`

## 延伸阅读

- [贡献与提交流程](workflow.md)
- [WebUI 插件配置（后端）](../common/webui/README.md)
- [本地开发环境](environment.md)
