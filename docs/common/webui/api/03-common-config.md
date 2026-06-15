# 通用配置

WebUI「通用配置」各段通过统一 REST 暴露；段定义在 `src/console/webui/env_sections.py`。

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/common-config/sections` | | 段元数据列表（id、标题、说明） |
| GET | `/common-config/{section_id}` | | 段内字段与当前值 |
| PUT | `/common-config/{section_id}` | 是 | Body `{"values": {...}}` |
| POST | `/common-config/service_gateways/connectivity-check` | 是 | 服务网关草稿连通性探测 |

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

## 前端对应

- `fetchCommonConfigSections`、`fetchCommonConfigSection`、`putCommonConfigSection`
- `postServiceGatewaysConnectivityCheck`

实现：`extended_api.py` + `env_sections.py`；网关探测 `src/plugins/connectivity/`、`service_gateways_section.py`。
