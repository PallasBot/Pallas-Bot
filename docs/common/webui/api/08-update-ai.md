# 更新与 AI 扩展

本页覆盖 WebUI / Bot 更新接口，以及 **Pallas-Bot-AI**（媒体 Runtime / 遗留 RWKV）扩展接口。普通 `@` 聊天走 Bot Provider，在侧栏 **AI 配置** 配接入即可，**不要求**本页 `/ai-extension/*` 或 `:9099` 可达。

## WebUI / Bot 更新

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/update/check` | | WebUI dist 发行版检查（默认产物 `public-react/`） |
| POST | `/update/apply` | 是 | 拉取并应用 WebUI 更新 |
| GET | `/update/bot/check` | | 主仓 Bot 版本检查 |
| GET | `/update/bot/config-migration/check` | | 配置迁移检查 |
| POST | `/update/bot/config-migration/apply` | 是 | 应用配置迁移 |
| POST | `/update/bot/apply` | 是 | 应用 Bot 更新；Docker 仅支持官方 Release 覆盖 |
| GET | `/update/git/bot/history` | | Git 历史，或 Docker 下的 GitHub Release 历史 |
| POST | `/update/git/bot/apply` | 是 | 应用指定 Release / Commit；Docker 拒绝 Commit 与 force |

写操作可能耗时较长；前端需处理进度与错误 `detail`。

## AI 扩展（Pallas-Bot-AI）

面向唱歌 / TTS 等媒体任务与遗留 RWKV；不是普通聊天 Provider。

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/ai-extension/config` | | 扩展配置 |
| PUT | `/ai-extension/config` | 是 | 保存配置 |
| POST | `/ai-extension/test` | 是 | 探测 AI 服务 |
| GET | `/ai-extension/install/status` | | 源码安装状态（是否已检测到 AI 仓、可否 clone/bootstrap/update） |
| POST | `/ai-extension/install` | 是 | 异步安装：`clone` / `bootstrap` / `clone_and_bootstrap` / `update`（托管目录 pull + bootstrap；SSE job） |
| GET | `/ai-extension/install/jobs/{id}/stream` | | 安装进度 SSE；成功时可能写回默认 `ai_extension.json` / `AI_SERVER_*` |
| GET | `/ai-extension/logs` | | 扩展日志 tail（kind: uvicorn / celery / celery-media） |
| GET | `/ai-extension/logs/stream` | | 扩展日志 SSE 实时流 |
| GET | `/ai-extension/ncm/status` | | 网易云登录状态 |
| POST | `/ai-extension/ncm/send-sms` | 是 | 发送验证码 |
| POST | `/ai-extension/ncm/verify-sms` | 是 | 验证登录 |
| POST | `/ai-extension/ncm/logout` | 是 | 退出 NCM |

配置落盘 `data/pb_webui/ai_extension.json`（见仓库 `config/ai_extension.example.json`）。源码一键安装入口在 WebUI **AI 配置 · 连接**。Docker 下 AI Runtime、Redis 与 Ollama 是 Compose 管理的外部服务，上述安装接口不操作其容器。

### Bearer Token 与运维日志

| 侧 | 配置项 | 说明 |
| --- | --- | --- |
| AI 服务 | `PALLAS_AI_API_TOKEN`（`.env`） | 非空时 `GET /api/ops/logs` 要求 `Authorization: Bearer <token>` |
| Bot WebUI | `token`（**AI 配置** · AI 服务） | 与 AI 侧**相同**；Bot 拉取远端日志时自动携带 |

两端 token **须一致**；AI 侧留空则不对 Bearer 校验（仅建议本地调试）。示例见 [Pallas-Bot-AI Deployment](https://github.com/PallasBot/Pallas-Bot-AI/blob/main/docs/Deployment.md#api-bearer-token)。

Bot 读日志顺序：本机落盘路径 → AI `GET /api/ops/logs` → 报错提示。

## 前端对应

- `UpdatePage`：`fetchUpdateCheck`、`postUpdateApply`、`fetchBotUpdateCheck` 等
- **AI 配置**（连接 / 媒体服务）：`fetchAiExtensionConfig`、`putAiExtensionConfig` 等

实现：`update_api.py` + `ai_extension_api.py` + `pallas_webui/manager.py`（GitHub Release 拉取）。

AI 仓库：[Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。
