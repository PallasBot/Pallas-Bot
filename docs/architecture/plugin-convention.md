# 插件目录约定

本文档约束 `src/plugins/*` 下的插件组织方式，目标是降低维护成本并提升新功能接入效率。该约定对新增插件和新增模块即时生效，历史插件按“改到再搬”渐进迁移。

## 最小插件结构

每个插件至少包含：

- `__init__.py`: 插件注册与对外入口
- `config.py`: 插件配置项定义

说明：将注册与配置显式化，可减少“配置在哪里声明”的搜索成本。

## 推荐扩展结构（按需）

当插件复杂度上升时，优先按功能拆分文件；仅在逻辑边界已经清晰且持续增长时，再引入通用分层目录：

- 功能分层（首选）：按业务能力拆分，例如 `plugin_manager.py`、`renderer.py`、`ban_manager.py`、`speaker.py`
- `handlers.py`: 事件/命令处理逻辑（按需）
- `models.py`: 领域模型或数据结构（按需）
- `services/`: 业务服务层（可选，适用于复杂逻辑持续增长）
- `repositories.py`: 持久化访问封装（可选，适用于数据访问复杂度上升）

> 不要求一次性改造历史插件；优先对新增插件和正在修改的插件执行。

## 代码组织原则

1. `__init__.py` 尽量保持轻量，避免堆积大量业务实现
2. 配置读取与默认值统一放在 `config.py`
3. 优先采用“按功能分层”的文件组织方式，命名直接体现业务能力
4. 当某类逻辑边界清晰、可复用且持续增长时，再引入 `services/`、`repositories.py` 等通用分层
5. 插件内部私有能力优先放插件目录；跨插件复用后再提取到 `src/common/`
6. 避免“超大单文件”，单文件过长时按职责拆分

## 插件路径约定

- 持久化数据使用 `data/<plugin_name>/...`。
- 资源文件使用全局目录 `resource/...`。
- 插件代码中优先通过 `src/common/paths/`（包 `src.common.paths`）的统一 helper 获取路径，不直接硬编码相对路径字符串。

说明：这样做可以避免运行目录变化导致路径漂移，也能统一备份与清理策略。

项目内实际示例：

- `src/plugins/greeting/__init__.py` 使用 `plugin_data_dir("greeting")` 作为插件数据目录入口。
- `src/plugins/greeting/voice.py` 使用 `resource_dir("voices")` 读取语音资源目录。
- `src/plugins/help/renderer.py` 与 `src/plugins/help/plugin_manager.py` 使用 `plugin_data_dir("help")` 管理缓存目录。
- `src/plugins/request_handler/__init__.py` 使用 `plugin_data_dir("request_handler")` 管理申请缓存目录。
- `src/common/paths/` 提供统一路径 helper，作为插件路径访问的推荐入口。

## 命名建议

- 文件名优先使用语义名：`handlers.py`、`speaker.py`、`ban_manager.py`
- 同层目录命名保持一致风格（小写 + 下划线）
- 避免缩写命名，除非是领域内通用缩写

## 测试配套约定

- 插件测试放在 `tests/plugins/<plugin_name>/`
- 新增行为优先附带最小可验证测试
- 历史问题应在 PR 说明中标注为“历史问题”或“本次引入问题”

## 迁移策略（建议）

1. 先新增约定，不直接重排历史目录
2. 先从高频改动插件开始（如 `greeting`、`repeater`）
3. 每次仅做一类整理：要么拆文件，要么迁文档，要么补测试
