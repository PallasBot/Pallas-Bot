# Changelog

## [4.0.1] - 2026-07-20

### Added

- Git 镜像：支持 GitHub 镜像源，并在控制台可配置
- 社区中心：WebUI 连通检测 API（含 OpenAPI 导出）
- WebUI BFF：媒体模型与 LLM 配置分家；Git 镜像相关增强
- AI Runtime 总览：上报画画 `draw_runtime_mode`（区分插件直通与 AI 绘图队列）

### Fixed

- 语料贡献时强制 re-enroll，避免贡献后未重新入队
- WebUI 启动时预创建并挂载 `store-assets`，避免官方插件封面被 SPA catch-all 当成 HTML
- AI 扩展默认健康路径改为 `/health`
- WebUI 保存 Literal 数字枚举时，字符串（如 `"1800"`）coerce 为 int，避免 400
- docs 分支 CI：改为 tip 镜像，避免反复 merge 分叉

### Changed

- 同步控制台 OpenAPI（含 git-mirror 等）

### 文档

- README 补充 Notion 牛牛协作区邀请链接
- 修正 Pallas-Bot-AI 外链分支为 `master`

## [4.0.0] - 2026-07-19

### Added

- 内核目录 `pallas/` + 内置插件 `packages/`；移除历史 `src/` 布局
- 稳定扩展入口 `pallas.api.*`（commands / config / perm / limits / metadata / paths / storage 等）
- `pallas-core` PyPI 包（`scripts/build_core.sh`；tag `v*` 触发 `.github/workflows/publish-pypi-core.yml`）
- 官方插件安装：`uv run pallas ext install`、控制台插件商店
- 配置合并：`config/pallas.toml` + `data/pallas_config/webui.json`（WebUI 落盘优先）
- 首次 Setup Wizard、AI 配置体检向导（WebUI）
- OpenAPI 导出 `openspec/pallas-console-v1.json` 与 WebUI codegen 客户端
- LLM capability 信封统一；AI runtime health 单一事实源（插件熔断去重）
- AI Runtime 总览页 `/ai/runtime`
- 插件治理工作区（权限 / 冷却 / 运行开关同屏）
- `PALLAS_DUPLICATE_PREFIX_STRICT` 生产门禁（重复前缀）

### Changed

- 默认仅加载 **core 插件**；玩法 / 协议 / AI 媒体等改 **官方插件**（pip）
- 智能接话依赖 **Pallas-Bot-AI 4.0+**；`CHAT_ENABLE` / `OLLAMA_*` → `LLM_*`（见 [ollama 迁移](docs/guide/llm-migrate-from-ollama.md)）
- WebUI 窄屏断点 ≤560px 规范（cmd 矩阵、插件配置、商店等）

### Removed

- 3.x 内置玩法插件直载（需安装对应 `pallas-plugin-*` 扩展）
- 插件侧自建 AI circuit 回退（改读 `pallas.api.ai_runtime_health`）

### 升级

见 [4.0 启动说明](docs/guide/4.0-start.md) 与 [4.0 迁移指南](docs/guide/4.0-migration.md)。

[4.0.1]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/PallasBot/Pallas-Bot/compare/v3.9.3...v4.0.0
