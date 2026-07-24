# 通用配置

WebUI「通用配置」各段通过统一 REST 暴露；段定义在 `src/console/webui/env_sections.py`。

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/common-config/sections` | | 段元数据列表（id、标题、说明） |
| GET | `/common-config/{section_id}` | | 段内字段与当前值 |
| PUT | `/common-config/{section_id}` | 是 | Body `{"values": {...}}` |
| POST | `/common-config/service_gateways/connectivity-check` | 是 | 服务网关草稿连通性探测 |
| GET | `/common-config/llm/runtime-overview` | | 聚合 AI health、模型、任务统计、conversation kernel |

## 常见 `section_id`

| ID | 用途 |
| --- | --- |
| `cmd_perm` | 命令权限覆盖矩阵 |
| `control_plane` | 联邦控制 |
| `corpus_federation` | 语料联邦 |
| `community_stats` | 在线统计与社区主站 |
| `ingress_fanout` | 入站全员同响口令 |
| `ingress_dispatch` | 入站调度运行时 |
| `repeater_learn` | 复读后台学习 |
| `message_scrub` | 消息审查 |
| `service_gateways` | 画画 / MAA / 点歌等网关 URL |
| `pallas_webui` / `pallas_protocol` / `help` | 对应插件控制台子集 |

PUT 落盘 `webui.json`；各段 `apply_webui_env_section_patch` 内触发对应 reload（如 cmd_perm 清缓存、message_scrub 热读）。

## `service_gateways/connectivity-check` 返回要点

该接口返回：

- `lines`: 面向文本展示的探测摘要
- `results`: 结构化探测结果数组

其中 `results[*]` 目前至少可能包含以下运行时契约字段：

- `runtime_state`
- `runtime_detail`
- `capability_id`
- `capability_group`
- `runtime_type`
- `failure_class`
- `health_state`
- `circuit_state`
- `consecutive_failures`
- `recent_failure_class`
- `queue_load_hint`

说明：

- `capability_*` / `runtime_type` 对齐 AI runtime capability 规格，用于稳定标识能力身份。
- `failure_class` / `health_state` / `circuit_state` 对齐统一运行时词汇，供 WebUI、日志与后续 AI 仓契约共用。
- 不同探测项可按能力成熟度返回字段子集；缺失字段表示当前探测源尚未提供，而非协议保留不用。

## `llm/runtime-overview` 返回要点

该接口聚合现有只读接口，供单页大盘直接消费，主要字段：

- `health`
  - `ok` / `url` / `status_code` / `error`
  - `llm_runtime_detail`
  - `llm_health`
  - `image_health`
  - `tts_health`
  - `media_tasks`
- `model_admin`
- `task_stats`
- `conversation_kernel`

注意：

- 这是**聚合视图**，不是新的状态机事实源。
- 各子字段仍沿用 AI runtime 既有健康语义，如 `health_state`、`circuit_state`、`degraded_state`。

## 媒体权重与模型管理

Bot 代理 AI Runtime（需媒体服务可达）：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/common-config/llm/media-assets/status` | 资源包就绪 / 大小 / download_allowed / delete_allowed |
| POST | `/common-config/llm/media-assets/download` | Body 可选 `{ "assets": ["tts", ...] }`；缺省下全部缺失 |
| POST | `/common-config/llm/media-assets/delete` | Body `{ "assets": [...] }`（仅源码可写） |
| GET | `/common-config/llm/media-assets/download/jobs/{job_id}` | 下载任务进度 |
| GET | `/common-config/llm/media-models/sing/speakers` | 说话人清单 |
| GET | `/common-config/llm/media-models/sing/backends` | SVC backend 清单与 preferred |
| PUT | `/common-config/llm/media-models/sing/defaults` | `{ "default_speaker" }` 和/或 `{ "preferred_backend" }`（空串=自动 fallback） |
| GET | `/common-config/llm/media-models/tts/voices` | TTS 参考音频清单 |
| PUT | `/common-config/llm/media-models/tts/defaults` | `ref_audio_path` / `prompt_text` 等 |

WebUI「能力包」页消费上述接口。默认配置落在 AI 侧 `data/media_models.json`。

## 前端对应

- `fetchCommonConfigSections`、`fetchCommonConfigSection`、`putCommonConfigSection`
- `postServiceGatewaysConnectivityCheck`

实现：`extended_api.py` + `env_sections.py`；网关探测 `src/features/service_gateways/`、`service_gateways_section.py`。
