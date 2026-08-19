# Pallas API 总览

`pallas.api` 是插件可依赖的 Python API 边界。先按本页选择依赖层级，再到 [pallas.api Cookbook](/developer/plugin-development/pallas-api-cookbook) 查具体接入方式和示例。

## 依赖层级

| 层级 | 可用对象 | 适用范围 |
| --- | --- | --- |
| L1 | `pallas.api.commands`、`config`、`runtime` 等 | 社区、站点、官方和内置插件的稳定入口。 |
| L2 | `pallas.api.platform` | 仅官方或内置插件；确有多 Bot、分片、舰队或媒体 callback 协作需求时使用。 |
| L3 | `pallas.core.*`、`pallas.console.*`、深层 `pallas.product.*` | 内部实现；不得被社区插件当作长期依赖。 |

`pallas.api` 本身不聚合符号，从具体子模块 import。L1 的公开符号以模块 `__all__` 为准；`ai_runtime_health` 没有 `__all__`，以该模块中面向插件的健康查询函数为准。L2 的完整导出表见 [Platform API](platform-api.md)，内部边界见 [Internal API](internal-api.md)。

## 模块地图

### 命令、配置与权限

| 模块 | 用途 | 何时使用 |
| --- | --- | --- |
| `pallas.api.commands` | 命令声明、handler 上下文、别名绑定与回复目标判断。 | 编写群聊、私聊或通用消息命令。 |
| `pallas.api.config` | 插件配置、热重载、命令前缀和仓库设置读取。 | 增加插件配置页，或解析统一命令前缀。 |
| `pallas.api.perm` | 命令权限、ACL 与帮助菜单可见性。 | 声明或运行时判断命令权限。 |
| `pallas.api.limits` | 冷却、频率限制与对应 WebUI 元数据。 | 需要给命令添加可配置频率限制。 |
| `pallas.api.metadata` | 帮助文案、场景和知识源元数据。 | 编写 `PluginMetadata`、命令菜单或知识源声明。 |

命令、权限和元数据的写法见 [Cookbook](/developer/plugin-development/pallas-api-cookbook) 与 [cmd_perm](/common/cmd_perm)。

### 消息与运行时

| 模块 | 用途 | 何时使用 |
| --- | --- | --- |
| `pallas.api.runtime` | 声明式 direct 命令、统一回复、延后效果与持久化工作任务。 | 精确文本或前缀命令，且权限与副作用边界清晰。 |
| `pallas.api.messages` | 上游错误归类和面向用户的脱敏失败消息。 | 调用外部服务后需要显示安全、可理解的错误。 |
| `pallas.api.safety` | 消息审查拦截与日志预览。 | 聊天、画图等需遵守消息审查的可见输出。 |
| `pallas.api.media` | 参考图 token、data URL 与媒体字节解析。 | 画图、图像编辑等需处理用户提供的参考图。 |

复杂 matcher、多步会话和 `@` 语义仍使用 NoneBot matcher；选择规则和 direct 示例见 [Cookbook · 精确命令与统一运行时](/developer/plugin-development/pallas-api-cookbook#精确命令与统一运行时)。

### 存储与服务能力

| 模块 | 用途 | 何时使用 |
| --- | --- | --- |
| `pallas.api.storage` | 按部署或群隔离的插件存储与 WebUI 列表元数据。 | 保存插件状态或设置。 |
| `pallas.api.paths` | 插件数据目录和包内资源目录。 | 读写插件自己的数据或静态资源。 |
| `pallas.api.probe` | 服务连通探测结果及其格式化。 | 在插件 WebUI 展示外部服务健康情况。 |
| `pallas.api.ai_runtime_health` | 从 AI `/health` 缓存读取媒体或 LLM 熔断状态。 | 媒体能力需根据 AI runtime 降级或熔断。 |
| `pallas.api.llm` | 已配置 LLM Provider 的查找、密钥和基址解析。 | 插件确需通过已配置 Provider 调用其兼容 API。 |
| `pallas.api.presence` | Bot 在本地或集群中的连接态查询。 | 分片或多 Bot 场景下选择可发送的 Bot。 |

普通聊天由内核 Agent / Provider 路径处理；插件不要绕过产品层自行拼接聊天调用。AI 健康和 Provider 解析的入口见 [Cookbook](/developer/plugin-development/pallas-api-cookbook)。

### 通用工具与平台协作

| 模块 | 用途 | 何时使用 |
| --- | --- | --- |
| `pallas.api.utils` | HTTP 客户端、流下载、GitHub Release、邮件、私聊发送和 CQ 码转换等共享工具。 | 已有工具准确匹配需求时按需 import，不作为插件基础框架。 |
| `pallas.api.platform` | 舰队、分片、Bot 角色、代发、全局 claim 和媒体 callback 协作。 | 仅官方或内置插件，并且 L1 无法表达该平台协作。 |

使用 L2 前先阅读 [Platform API](platform-api.md)；若社区扩展确有缺口，应提出 L1 API 需求，而非直接 import 内部实现。

## 维护约定

- 新增可长期依赖的能力时，先放入语义明确的 `pallas.api` 模块，再补本页与 Cookbook。
- 新增 `pallas.api.platform` 导出时，同步更新 [Platform API](platform-api.md) 的导出表。
- 控制台 REST API 与本页不同：它是维护者向接口，见 [WebUI API](/common/webui/api/)。
