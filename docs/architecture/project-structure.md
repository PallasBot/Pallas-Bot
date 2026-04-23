# 项目结构约定

本文档用于统一仓库目录职责，减少“文件放哪儿”的沟通成本。该约定对新增内容即时生效；历史内容按“改到再搬”渐进调整，不要求一次性重构。

## 顶层目录职责

- `src/`: 业务源码
- `tests/`: 单元测试与集成测试
- `docs/`: 面向开发与部署的文档
- `tools/`: 维护脚本与辅助配置
- `.github/workflows/`: CI/CD 流水线
- `data/`: 运行期持久化数据（按插件分目录，如 `data/help/`）
- `resource/`: 项目静态资源（如语音、样式）

## 源码分层约定

- `src/common/`: 跨插件复用能力（如配置、数据库、工具函数）
- `src/plugins/`: 业务插件，按功能域拆分

约定原则：

1. 插件业务代码优先放在 `src/plugins/<plugin_name>/`
2. 可复用能力优先沉淀到 `src/common/`，避免在插件间复制
3. 新增目录时优先保持语义单一，避免“脚本+配置+文档”混放

补充说明：

- 插件持久化数据统一落在 `data/<plugin_name>/...`，原因是方便备份与按插件排障。
- 插件资源统一放在 `resource/...`，原因是便于复用并避免插件目录携带大体积二进制资产。

项目内实际示例：

- `data/greeting/`：`greeting` 插件的好友欢迎消息持久化目录。
- `data/help/`：`help` 插件的帮助图渲染缓存目录。
- `data/request_handler/`：`request_handler` 插件的待处理申请缓存目录。
- `resource/voices/`：`greeting` 使用的语音资源目录。
- `resource/styles/`：`help` 插件的样式资源目录。

## 测试目录约定

- 测试目录尽量镜像源码目录，例如：
  - `src/plugins/repeater/...` -> `tests/plugins/repeater/...`
  - `src/common/db/...` -> `tests/common/...`

这样可以降低定位测试与补测成本。

## 文档目录约定

- `docs/Deployment.md`、`docs/DockerDeployment.md`：部署类文档
- `docs/FAQ.md`：常见问题
- `docs/architecture/`：架构与约定文档（本文件所在目录）
- `docs/plugins/`：插件专项说明（后续可逐步迁入）

当前已迁移示例：

- `bot_status` 插件文档已迁移到 `docs/plugins/bot_status.md`

## tools 目录约定

为避免语义混杂，当前按以下方式拆分：

- `tools/scripts/`: 可执行脚本（如备份、清理、迁移）
- `tools/config/`: 仅工具侧配置文件

## 根目录协作文件

- `AGENTS.md` 建议保留在仓库根目录，便于贡献者与 Agent 统一读取协作约定。
- `.pre-commit-config.yaml` 与 `.pre-commit-ci.yaml` 建议保留在仓库根目录，便于工具默认发现与执行。

## 渐进落地策略

1. 新增文件按本约定放置
2. 历史文件在“改到再搬”的原则下逐步迁移
3. 每次 PR 只做小步调整，避免大规模无关重排
