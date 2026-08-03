# Changelog

## [4.1.26] - 2026-08-03

### 更新公告

- 直聊清理无关人设、收尾提示和同伴账号列表，短消息更容易自然接话
- 群内共同事件可自动摘要进记忆，后续对话能延续上下文
- 主持活动优先识别决斗 QTE 别名，避免被通用入口抢走
- LLM 调试记录隐藏退役的人设塑形正文，并显示清理观测结果
- 捆绑控制台 WebUI v0.8.22

### Added

- 群内共同事件自动摘要记忆。
- 直聊匿名离线质量评测工具。

### Fixed

- 直聊仅在明确提及同伴账号时才注入消歧信息。
- 决斗 QTE 别名优先进入主持活动处理。

## [4.1.25] - 2026-08-03

### 更新公告

- 帮助功能详情正文按段落和实际宽度完整换行，长音色列表不再截断
- 联邦部署会标记未支持新版命令能力协议的旧端，并提示及时升级，降低未知命令被旧端抢占的风险
- 捆绑控制台 WebUI **v0.8.21**

### Fixed

- 帮助功能详情正文与长列表完整换行
- 联邦命令能力协议兼容状态识别

## [4.1.24] - 2026-08-02

### 更新公告

- 多牛齐声时，各账号轮转分配不同语句，少机场景更不易齐声同句
- 控制台更新页可查看 Bot Release / Commit 历史并定向更新（需配套控制台 ≥ 0.8.18）
- 库内未连接的 Bot 也会尽量补全昵称资料
- 联邦下显式命令能力优先归属，避免未宣告端抢走自定义前缀
- 捆绑控制台 WebUI **v0.8.18**

### Added

- Bot git 管理台 API（Release / Commit 历史与定向更新）

### Fixed

- 库内未连接 Bot 补全昵称资料
- 联邦显式命令能力优先归属

### Changed

- 齐声 fanout 按 peer 轮转分配语句

## [4.1.23] - 2026-08-01

### 更新公告

- 唱歌「音频映射」自定义命令前缀（如「一歌」）会进入路由识别，不再被当成闲聊丢掉
- 需配套更新官方扩展 `pallas-plugin-ai-media` ≥ 4.3.2（映射同步写入 ingress 前缀）
- 捆绑控制台 WebUI **v0.8.17**

### Fixed

- ingress 命令明文识别纳入插件显式 `command_prefixes`

### Changed

- 与唱歌音频映射自定义前缀配套

## [4.1.22] - 2026-08-01

### 更新公告

- 本地 AI Runtime 宣称在跑但健康检查失败时，控制台「启动」会先停再起，避免空操作卡在异常
- 回环健康检查不再走系统 HTTP 代理，减少误报 502
- 社区商店列表支持 `skip_assets` 并合并资源刷新
- 捆绑控制台 WebUI **v0.8.16**

### Fixed

- 不健康 Runtime 启动时先 `stop` 再 `start`
- 回环 `/health` 与扩展连通性测试绕过代理

### Changed

- 社区商店列表 `skip_assets` 与资源刷新合并

## [4.1.21] - 2026-08-01

### 更新公告

- AI Runtime 启停后短轮询再返回状态，控制台更不易卡在「启动中 / 已停止」错态
- 唱歌可为每个音色单独指定优先推理后端（需配套控制台与较新 AI Runtime）
- 补充 DDSP 多版本手动安装说明；官方 `pallas` 对应 6.2
- 捆绑控制台 WebUI **v0.8.14**

### Added

- 控制台 BFF 透传 `speaker_backends`

### Fixed

- Runtime 启停后短轮询 `ai_runtime_status` 再返回

### Changed

- AI Runtime / 唱歌文档：DDSP 多版本与按音色绑定后端

## [4.1.20] - 2026-08-01

### 更新公告

- 版本检查不再走已失效的 moeyy.cn GitHub 代理；多镜像都失败时错误提示指向优先源，不易被末位失效代理带偏
- 捆绑控制台 WebUI **v0.8.13**

### Fixed

- 移除内置失效镜像 `moeyy.cn/gh-proxy`
- 全部镜像失败时抛出优先镜像的异常，避免报错 URL 误导

## [4.1.19] - 2026-08-01

### 更新公告

- AI 回调会先原子领取任务再投递，超时重试时不再连发多条相同语音
- AI Runtime GPU 说明更新为 torch 2.7.1 + cu128，支持 RTX 50 系（需重装 GPU 依赖）
- 捆绑控制台 WebUI **v0.8.13**

### Fixed

- AI 回调原子 claim，避免并发/重试重复发语音或图片

### Changed

- AI Runtime 文档注明 GPU 线 cu128 与 RTX 50 支持

## [4.1.18] - 2026-08-01

### 更新公告

- 控制台可断开外置协议账号的本机 OneBot WS；连接列表带出 WS 端口
- 短窗自动母题去重，表达库换说法更稳
- 社区统计 `/v1/stats` 回退时能推断语料是否开启
- 捆绑控制台 WebUI **v0.8.13**

### Added

- `POST /pallas/api/bots/{qq}/disconnect-ws` 断开本机 WS
- 连接列表 `ws_port` / `shard_id` 供控制台展示

### Fixed

- 社区统计 `/v1/stats` 回退时推断 `corpus_enabled`

### Changed

- LLM 短窗自动母题去重并强化表达库换说法

## [4.1.17] - 2026-07-31

### 更新公告

- 控制台可查看并对齐 AI 回调端口；异步任务切页后可续看进度
- DeepSeek 等可统一配置思考强度，并支持思考与工具同开；Responses 工具入参更稳
- 本机 Embedding 可走 Redis 辅进程，减轻对话热路径压力
- CLI：`unified` / 辅进程启停说明更清晰，可用 `pallas logs` 看日志
- 回复路径统计只在真正发出时记账，不再把「尝试现编」算进去
- 运行日志续行合并更准；语料扫库不再重复 init 卡死连接
- 捆绑控制台 WebUI **v0.8.12**

### Added

- 控制台 AI 回调端口展示与对齐
- `/jobs/active` 续看异步 job 进度
- 思考强度统一映射；DeepSeek 思考 + tools
- Responses 扁平 tools 与 reasoning 回传
- 本机 Embedding Redis 辅进程
- `pallas logs` 与 unified/aux 生命周期叙事

### Fixed

- 回复路径在提交前虚记；callback 成功且带明确 `llm_route` 再记
- 日志续行仅合并 ≥2 空白缩进
- 语料扫库重复 init 导致 idle-in-transaction
- 唱歌映射字段文案「命令」→「音色」
- 图片缓存失败日志带异常类型

### Changed

- Agent / 面向用户用语约定同步

## [4.1.16] - 2026-07-30

### 更新公告

- 控制台可自动检查并应用 WebUI / Bot / 插件更新；「立即检查并应用」改为后台任务，避免超时
- 超管私聊「牛牛更新」可开关自动更新、汇报与汇报用牛；检查回复更短；完整用法发「牛牛更新 帮助」
- 运行状态改为群内/私聊发 `#pallas`；控制台/更新/重启等管理入口在超管帮助里按条可见
- 托管 AI Runtime 支持控制台一键更新；Windows 下 Git Bash / 编码 / 环境变量更稳，缺 ffmpeg 会提示
- 酒后对话可再附带语音；TTS 支持中翻日（成功后按日语合成）
- 群记忆 Embedding：可选远程 / 本机 / 占位；线路可复用 Provider 名册；换模型会回填；控制台有探测
- 「有什么功能」一类盘点会先查再答；工具命中时不再被语料抢答；叫「牛牛」做表情等更不易误触
- 入站过载时默认降质接话；路由与复读查库更快；多机时命令归属按本群在场过滤
- 捆绑控制台 WebUI **v0.8.11**

### Added

- 控制台自动更新（WebUI / Bot / 插件）与异步「立即检查并应用」任务
- `牛牛更新`：自动开关、汇报、汇报用牛；超管帮助条目级可见管理命令
- AI Runtime 一键更新与 `has_update` 探测
- EmbeddingProvider（远程 / 本机 / 占位）、诊断 API、feedback trigger 回填、线路备线字段
- 酒后对话附带语音；TTS 中翻日配置接口
- 盘点意图打开查询工具通道；工具 `capabilities` 与盘点命中指标
- ingress hotpath 指标、过载默认降质接话

### Fixed

- 通称「牛牛」只卡前界，恢复句首口令唤起
- Embedding 选 openai 时端点字段与语义诊断；记忆图谱 PG 写入补 commit
- 盘点只开查询工具；命中工具时跳过语料 polish；命令工具只剥开头唤醒 `@bot`
- 工具软召回祈使词干加分，降低误触
- Runtime 在 `api.pid` 失效时回退 HTTP 探活；启动子进程剥离 `VIRTUAL_ENV` 并提示 ffmpeg
- Windows：bootstrap UTF-8、优先 Git Bash / WSL 路径
- 联邦命令归属按本群在场过滤
- 帮助图缓存带文案指纹；更新帮助不受应用冷却；插件详情功能卡展示简介
- `chat_drop_on_overload` 保存路由登记；分片 restart 默认 force

### Changed

- 运行状态入口改为 `#pallas`（默认权限 bot_moderator）
- 发行捆绑控制台取 WebUI **v0.8.11**

### Performance

- 路由 Trie、明文缓存与分词 LRU；复读 bundle 空结果负缓存
- 接话语义热路径减负

## [4.1.15] - 2026-07-30

### 更新公告

- 多机共池时按「命令能力」归属：只有宣称能处理该命令的部署才会当主人（如本地塔罗）
- 控制台可开「命令群归属优先本机」：本机能处理时不再轮给对端
- 群归属默认轮换由 12 小时改为 2 小时
- 文案统一：插件触发称「命令」，控制台登录称「密钥」
- 捆绑控制台 WebUI **v0.8.10**

### Added

- 联邦心跳 `command_capabilities` 与按能力过滤归属环
- `PALLAS_FEDERATE_PREFER_LOCAL_OWNER` / 多机协同「本机优先」开关

### Changed

- `PALLAS_FEDERATE_OWNER_ROTATE_SEC` 默认 `7200`（2h）
- 面向用户的「口令」用语改为「命令」；控制台登录改为「密钥」（社区访问口令除外）
- 发行捆绑控制台取 WebUI **v0.8.10**

## [4.1.14] - 2026-07-29

### 更新公告

- 多机共池时，群归属默认约每 12 小时轮换，避免热闹群长期钉在一台
- 闲聊不再粘死归属；过载时优先保住口令，复读查库有短超时与缓存
- 人设自称拆成通称与专属，复合昵称可短别名；叫名与让出更准
- 控制台可看 AI Runtime 安装进度与引导日志流
- `redis` 纳入主依赖，多机协同不再因缺客户端关掉联邦
- 捆绑控制台 WebUI **v0.8.9**

### Added

- 群归属轮换（`PALLAS_FEDERATE_OWNER_ROTATE_SEC`，默认 12h）
- AI Runtime 安装进度 / bootstrap SSE
- 人设通称/专属自称、接话指纹与短窗母题抑制

### Fixed

- providers 按磁盘 revision 热载
- 表情工具参数清洗；list/search 不垫自己
- 通称「牛牛」按词界匹配；别名让出仅认专属命中

### Changed

- 入站：闲聊/被动路径收紧；过载可跳过闲聊 matcher
- 发行捆绑控制台取 WebUI **v0.8.9**

## [4.1.13] - 2026-07-29

### 更新公告

- Windows 下修复因 `fcntl` 缺失导致的启动/日统计异常
- 默认支持无斜杠中文口令（如「牛牛表情」）；可在牛牛核心「命令口令」调整（须重启）
- 帮助总览取消翻页，按分组连续编号
- 多机协同开启时，入池密钥为空可在启动时自动从社区中心写入并拉取配置
- 控制台数据库页可查看语料各子表行数
- 捆绑控制台 WebUI **v0.8.8**

### Fixed

- Windows：跨平台文件锁与进程探测，避免 `fcntl` 报错
- ingress：`menu_data` 中「命令 + 参数」文案不再整段丢失路由前缀；别名仅按两侧空白的 `/` 拆分

### Added

- `COMMAND_START` 发行缺省含空前缀；WebUI 牛牛核心可配
- 协同入池默认自动 bootstrap（密钥与去重配置）
- 数据库页语料子表行数

### Changed

- 帮助总览取消翻页
- 发行捆绑控制台取 WebUI **v0.8.8**

## [4.1.12] - 2026-07-28

### 更新公告

- 智能对话可在控制台配置外部 MCP，并挂到工具目录
- MCP 连接改为常驻复用（stdio / HTTP），避免每次冷启动
- 注册失败原因可在工具策略里看到
- 捆绑控制台 WebUI **v0.8.7**

### Added

- `LLM_MCP_SERVERS` / `LLM_MCP_HTTP_ALLOWLIST` 经 WebUI llm 段读写；变更后重注册工具

### Changed

- MCP stdio/HTTP 常驻 session；snapshot 含 sessions
- 发行捆绑控制台取 WebUI **v0.8.7**

## [4.1.11] - 2026-07-28

### 更新公告

- 运行日志：分片合并时间线更稳（ISO 启动行归一）；SSE 跳过 hub-file 双推并缓冲半行
- 范围切面改为「消息 / 控制台 / 其它」（新日志打 facet；旧条目归入其它）
- 支持导出纯文本运行日志；补充落盘位置与导出说明
- LLM：提供方探测回落收紧；统一错误详情；支持禁用项与多密钥草稿连通测试
- 其它：加大社区语料超时默认值；对齐 pip 插件短 id；ingress/Matcher 降噪；镜像拉取日志打印实际 mirror
- 捆绑控制台 WebUI **v0.8.6**

### Added

- `GET /logs/export` 纯文本导出
- 日志条目 `facet`（message / console / other）与范围筛选

### Fixed

- 分片日志 ISO 启动行排序、SSE hub-file 双推与半行截断
- 分片来源归一与多行合并；ingress/access 降噪与入站颜色标签
- LLM 提供方错误与探测回落；插件短 id 与 plugin_storage 对齐

### Changed

- 日志范围由 webui/protocol 改为 message/console/other
- 发行捆绑控制台取 WebUI **v0.8.6**

## [4.1.10] - 2026-07-28

### 更新公告

- 插件商店：安装 / 更新 / 卸载走统一异步任务，可通过 SSE 推送进度
- LLM 计量：当日 token 与提供方调用优先用请求账本，重启后统计不再被偏少快照盖掉
- 分片部署下 worker 不再回灌共享计量，避免观测数字重复累加；小时趋势 by_hour 修复
- 知识库门控跳过记为 skip（不计入 miss）；别名点名让出 claim，续聊软窗按 bot 隔离
- 未安装协议插件时跳过 onebot 实例同步，accounts 仍可对齐
- 社区统计页加载更快，并补回 monitor 版本分布
- 捆绑控制台 WebUI **v0.8.4**

### Added

- 插件商店统一任务进度与异步更卸 API（含 OpenAPI）

### Fixed

- LLM：当日 token / 提供方调用优先账本；重启不缩水；分片不回灌共享计量；by_hour 趋势；知识库门控 skip
- 入口：别名点名让出 claim，续聊软窗按 bot 隔离
- 协议：未安装协议插件时跳过 onebot 同步
- 控制台：社区统计加载与 monitor 版本分布

### Changed

- 发行捆绑控制台取 WebUI **v0.8.4**

## [4.1.9] - 2026-07-27

### 更新公告

同一 Provider 可配置多把 API 密钥：第一位为主用，鉴权/限流等失败时按序换下一把。控制台密钥芯片可拖拽排序并标主用。捆绑 WebUI **v0.8.3**。

### Added

- Provider 多密钥有序故障转移（401 / 403 / 429 / 502 / 503）

### Changed

- 发行捆绑控制台取 WebUI **v0.8.3**

## [4.1.8] - 2026-07-27

本版相对 4.1.7：接入官方扩展「牛牛说」（侧车 TTS），去掉酒后对话附带语音；插件 / LLM / 控制台分层继续收紧。捆绑 WebUI **v0.8.2**。

### Added

- 官方「牛牛说」：`tts` 任务类型、语音投递与插件矩阵注册（依赖 `pallas-plugin-ai-media`）
- TTS / AI Runtime 文档与帮助入口

### Fixed

- `bytes_to_data_reference_url` 媒体导出
- 控制台 LLM 测试 patch 面；`ai_callback` 导入顺序

### Changed

- 移除 `CHAT_TTS_ENABLE` / 酒后附带语音路径
- 玩法插件 bundled；LLM / 配置 / 分片 / 控制台公开面收紧
- AI Runtime 文档去掉「绘图归属本仓」；链接改指向 `main`
- 发行捆绑控制台取 WebUI **v0.8.2**

## [4.1.7] - 2026-07-27

### 更新公告

本版让群聊人设更稳：少万能软答应、同句不复读、可按场合选口癖，并可选本轮动作决策与输出防火墙。控制台 AI 配置说明重写，更新页可直接弹出仓库 CHANGELOG。捆绑 WebUI **v0.8.0**。

#### 你会明显感觉到

- 少「行行行 / 还行吧 / 嗯？」一类垫词起手；人设不再示范这些万能软答应
- 同一句（或极近）再问时，会提示换说法，避免复读上一句
- 行为（怎么接）与措辞（口癖 / 临时风格）分层；口癖按场合选入，并有可恢复的效果反馈
- 可选：按当前牛格注入临时回复风格（默认约 1/4 轮，不固化为人设）
- 可选：本轮动作决策（回复 / 跳过 / 用工具 / 追问），默认关，走任务编排低档路由
- 可选：人设输出防火墙（提示词泄露、舞台动作、身份冲突、重复垫词），默认关，失败可有限重述
- 可维护场景正反例，仅在用户线索相关时注入，不会整段复读示例
- 更新页可拉取 Bot / WebUI 的 CHANGELOG 弹窗说明

#### 稳定性与运维

- LLM 任务路由与传输失败时的备用提供方链路更完整
- 远程社区语料投稿不再被并发预算静默跳过
- CLI / 分片脚本跨平台化（含 Windows `.cmd`）；unified 启停改 Python
- 启动时正确加载 emoji_reaction

### Added

#### 人设与对话治理

- 行为 / 措辞分层；按场合选入口癖与表达参考
- 同句重回防复读提示
- 牛格驱动的可配置临时回复风格变体
- 本轮动作决策层（REPLY / PASS / TOOL / FOLLOW_UP）
- 对话输出一致性防火墙与场景对话正反例库
- 措辞场合标签、效果反馈审计与可恢复写入

#### 控制台与更新

- `GET /pallas/api/update/changelog`：截取仓库 CHANGELOG 供更新页弹窗
- AI 配置字段说明面向新手重写（含人设防火墙等）

### Fixed

- 口癖场合匹配、场景化措辞选择、存储锁与反馈审计
- 防火墙：配置回显、工具重放防护、追踪脱敏、无关场景示例过滤
- 任务路由备用提供方与传输失败续链
- 远程语料并发预算导致投稿被静默跳过
- repeater 启动加载 emoji_reaction；CLI 跨平台启停

### Changed

- 人设不再示范垫词；发行捆绑控制台取 WebUI **v0.8.0**

## [4.1.6] - 2026-07-26

本版相对 4.1.5：发言感知（别名提及 / 氛围插嘴 / 续聊软窗）配置进 WebUI 对话策略。捆绑 WebUI **v0.7.12**（发版前需先合并并发布该 WebUI tag）。

### Added

- WebUI 暴露 `LLM_SPEAK_*` 发言感知开关与细调（总闸、别名提及、ambient、续聊软窗）

## [4.1.5] - 2026-07-26

本版相对 4.1.4：社交型 Agent 平台（观察队列 / 人物事实 / 口癖 / 任务编排）、LLM 动作与开口拆分、联网搜索与 Draw 连通修复；重复器接话 stage 收敛。捆绑 WebUI **v0.7.11**（人物 / 任务观测与口癖审批等；发版前需先发布该 WebUI tag）。

### Added

#### Agent 平台与记忆

- 记忆观察队列、Planner 与 lifecycle 检索
- 人物事实、跨群同意与群体画像
- 账号口癖候选库；成功回复抽短习惯后审批注入人设（非整句接话）
- 行动工具、任务编排与 Agent Platform 控制台 API
- 请求级 usage 账本与历史脏数据过滤

#### LLM 对话与工具

- 动作与开口拆分：工具结果经 `chat.reply` 发可见对白；可短 ack 或沉默
- 硬域未命中时按 hints / 描述软召回工具；记住已激活工具并补全追踪
- 统一重复器能力解析与阶段规划；复用聊天上下文与工具组装
- 嵌入检索能力映射；回退时停用语义检索

#### 文档

- 全站信息架构与社区投稿墙；AI 观测 / 联网搜索说明；Agent 架构与部署边界

### Fixed

- 联网搜索可正确选中并支持配置（含 Tavily 等）
- Draw 适配移除 `runtime_mode` 后的连通探测
- AI 口令派发透传原消息图 / @ 素材，并排除唤醒 @bot
- 压制动作后 `chat.reply` 元叙述废话

### Changed

- 收敛 LLM 接话 stage 与 lite 默认策略；移除旧 LLM 提交路径
- 文案「闲聊」改为「LLM 对话」；兼容会话档位标注 deprecated
- 发行捆绑控制台取 WebUI **v0.7.11**

## [4.1.4] - 2026-07-26

本版相对 4.1.3：数据库韧性与 Mongo→PG 迁移、口令工具多域召回与选型调试、同伴身份与输出闸、LLM 日级观测计数；控制台配套健康/后端切换与异步更新。捆绑 WebUI **v0.7.9**（迁移向导、可搜索 Combobox、工具选型预览等）。

### Added

#### 数据库

- 健康状态与热路径非关键门禁；低优先级写队列与 schema 步骤可观测
- 版本化 schema 注册；Mongo→PostgreSQL 控制台迁移任务（含热重绑尝试）
- 控制台：数据库健康与表白名单只读 API；后端切换与连通性探测

#### 口令工具与闲聊（LLM）

- 多域结构召回与工具选型打分；`tools.find` 全量回退检索
- 工具选型预览与 hints / 描述覆盖 API（控制台可调试口语选型）
- 插件工具声明式触发说法与口语召回；点歌等域收窄，避免 command 全家桶
- 同伴牛牛身份注入；输出旁白 / 填料闸
- `reply_gate` / 发言感知 / 选择性回复 / 工具链路日级观测计数

#### 控制台与插件

- 「应用 Bot 更新」改为异步 job，并上报真实进度百分比
- 插件配置 `ui_group` 分组（如 repeater / webui / help）

#### 捆绑控制台（WebUI v0.7.9）

- Mongo→PostgreSQL 迁移向导；数据库健康摘要与表白名单只读浏览
- Bot / 长列表选择改为可搜索 Combobox（≥8 显示搜索）；AI 观测群可搜可选
- 对话工具页：口语选型预览与 hints / 描述覆盖
- 工具条与配置弹窗体验（右钉操作、存储视图切换、群好友配置删除等）

### Fixed

- DeepSeek thinking 默认关闭，并正确回传 `reasoning_content`
- 口令工具回传歌名等结果字段
- 动态加载迁移脚本时先注册 `sys.modules`，避免重复导入失败
- SPA HTML 入口禁用长期缓存，降低发版后仍引用旧 hash 资源的概率
- 精简数据库后端探测与保存文案

### Changed

- 同步控制台 OpenAPI（迁移任务、工具预览与覆盖、数据库健康等）
- 发行捆绑控制台默认取 WebUI 最新 tag（本版 **v0.7.9**）

## [4.1.3] - 2026-07-25

### Changed

- 帮助总览菜单改为三列布局，并按版心收窄卡片与字号

## [4.1.2] - 2026-07-25

本版相对 4.1.1：闲聊更会「接话 / 认人 / 调工具」，控制台补齐工具与语料调试能力；捆绑 WebUI **v0.7.8**。

### Added

#### 闲聊与人设

- 群聊发言感知：别名提及、ambient 插嘴；硬触发后软窗口续聊
- 关系层：弱观察沉淀、人对语气偏置、称呼注入；登录昵称自称与 `self_aliases`
- 单群表达库接入牛格 / 情感装配；强场景接话双预算与反哺写回
- 会话工具轨迹 `tool_trace`（便于排障与历史回看）

#### 口令工具（LLM Tools）

- 插件可通过 `extra["llm_tools"]` 声明群口令工具；按话术 select 域注入
- 内置 / 官方扩展陆续开放（喝酒、帮助、轮盘、唱歌、画画等）；工具名兼容 DeepSeek 等 provider

#### 控制台 API

- LLM 工具只读清单；语料源详情 / chunk 预览 / 检索试探
- `provider_gateway` 主备线路声明；活跃群 DAG/MAG 与 AI 费用补齐
- 社区投稿墙代理 API

#### 其他

- 帮助图 v4 分组，插件 `help_tag` 覆盖

### Fixed

- 酒后对话启动加载；硬触发空回复兜底（避免已读不回）
- Provider 工具名去点号；thinking 与 `tool_choice=required` 冲突
- 检索降噪（memory/knowledge `min_score` 与查询门控）；表达回灌限频、抑制开场复读
- 僵尸 WS 隔离，避免假在线挡重新上号；ingress 预筛允许「命令+紧贴参数」
- 社区投稿：固定正式中心、可不选 Bot、默认昵称

### Changed

- 发行捆绑控制台默认取 WebUI 最新 tag（本版 **v0.7.8**）
- 官方扩展仓库迁至 `PallasBot/Plugin-*`

## [4.1.1] - 2026-07-24

### Fixed

- LLM：修复酒后对话因 `Bot` 仅在 TYPE_CHECKING 导入导致启动 NameError

## [4.1.0] - 2026-07-24

### Added

- LLM：内核直连 Provider / ops（模型管理、会话与指标），不再依赖 AI 仓中转
- LLM：记忆图谱（entity/edge）与 mid-term / session ops
- WebUI：LLM ops 与记忆图 API；发版从 WebUI 仓库根构建 React

### Changed

- AI Runtime / 文档：LLM 能力以 Bot 内核为准；AI 仓侧重媒体（唱歌 / TTS）
- Release：兼容 WebUI 根目录与旧 `react/` 子目录构建路径

### Removed

- 遗留登录页 HTML（`login_page.py`）及对应测试

## [4.0.3] - 2026-07-21

### Fixed

- LLM：Provider 模型列表改由 Bot 直连上游（不再经 AI 中转）
- CQ 段字段转义兼容 int，避免撤回等链路因 `at.qq` 等为整型而报错
- 分片日志：按 worker 隔离 traceback 合并；理清更新检查缓存兜底日志
- Docs 同步：补齐 VitePress 链接变换，避免 Docs CI 死链
- 同步控制台 OpenAPI，补齐 LLM Provider 模型发现接口

### 文档

- 补充社区插件发版后同步索引的步骤

## [4.0.2] - 2026-07-21

### Added

- LLM：结构化回复 PASS 与接话必要性门控，减少垫话与元问题胡编
- LLM：场景口气、注意力漂移约束；接话轻润色改用口语 expressor
- LLM：情境规则关键词热注入；反馈样本 BAD/OK 对照 few-shot
- LLM：可选错别字拆条、表情 fit 与回复效果评审
- LLM：`session_store` / 群记忆 / 关系便签支持 Mongo 后端

### Fixed

- LLM：Mongo 记忆与关系 ID 原子分配，并缓存 session 后端选择
- LLM：收紧接话门控，拦截垫词与元问题胡编

### Changed

- LLM：闭嘴关键词收敛到 `shut_up` 共用定义
- 同步控制台 OpenAPI；预提交可自动导出并联动 WebUI 类型

### 文档

- 补充 OpenAPI 双仓同步说明
- Release / 构建脚本：WebUI 解压路径改为 `data/pb_webui`，完善发版说明

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

[4.1.6]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.5...v4.1.6
[4.1.5]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.4...v4.1.5
[4.1.4]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.3...v4.1.4
[4.1.3]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.2...v4.1.3
[4.1.2]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.1...v4.1.2
[4.1.1]: https://github.com/PallasBot/Pallas-Bot/compare/v4.1.0...v4.1.1
[4.1.0]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.3...v4.1.0
[4.0.3]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.2...v4.0.3
[4.0.2]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.1...v4.0.2
[4.0.1]: https://github.com/PallasBot/Pallas-Bot/compare/v4.0.0...v4.0.1
[4.0.0]: https://github.com/PallasBot/Pallas-Bot/compare/v3.9.3...v4.0.0
