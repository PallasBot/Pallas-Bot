# 更新与 AI 扩展

## WebUI / Bot 更新

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/update/check` | | WebUI dist 发行版检查 |
| POST | `/update/apply` | 是 | 拉取并应用 WebUI 更新 |
| GET | `/update/bot/check` | | 主仓 Bot 版本检查 |
| GET | `/update/bot/config-migration/check` | | 配置迁移检查 |
| POST | `/update/bot/config-migration/apply` | 是 | 应用配置迁移 |
| POST | `/update/bot/apply` | 是 | 拉取/应用 Bot 更新（git/部署逻辑） |

写操作可能耗时较长；前端需处理进度与错误 `detail`。

## AI 扩展（Pallas-Bot-AI）

| 方法 | 路径 | 写 | 说明 |
| --- | --- | --- | --- |
| GET | `/ai-extension/config` | | 扩展配置 |
| PUT | `/ai-extension/config` | 是 | 保存配置 |
| POST | `/ai-extension/test` | 是 | 探测 AI 服务 |
| GET | `/ai-extension/logs` | | 扩展日志 tail |
| GET | `/ai-extension/ncm/status` | | 网易云登录状态 |
| POST | `/ai-extension/ncm/send-sms` | 是 | 发送验证码 |
| POST | `/ai-extension/ncm/verify-sms` | 是 | 验证登录 |
| POST | `/ai-extension/ncm/logout` | 是 | 退出 NCM |

配置落盘 `data/` 下 AI 扩展专用路径（见 `extended_api` 内 `_ai_extension_config_path`）。

## 前端对应

- `UpdatePage`：`fetchUpdateCheck`、`postUpdateApply`、`fetchBotUpdateCheck` 等
- `AiExtensionPage`：`fetchAiExtensionConfig`、`putAiExtensionConfig` 等

实现：`extended_api.py` + `pallas_webui/manager.py`（GitHub Release 拉取）。

AI 仓库：[Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI)。
