# 仓库结构

Pallas-Bot 多仓分工与主仓目录。

## 仓库

| 仓库 | 责任 |
| --- | --- |
| `Pallas-Bot` | 运行时、内核、内置插件、WebUI 后端、分片与治理 |
| `Pallas-Bot-WebUI` | 控制台前端源码 |
| `Pallas-Bot-AI` | AI / 媒体任务 runtime |
| 官方插件仓 | 独立能力包（如 duel、draw、maa、who-is-spy） |
| 社区扩展仓 | 第三方与站点定制 |
| `Pallas-Bot-Docs` | VitePress 站点（由主仓 `docs/` sync） |

## 主仓目录

| 路径 | 作用 | 典型修改者 |
| --- | --- | --- |
| `pallas/` | 内核、平台、产品、console | 平台维护者 |
| `packages/` | 内置插件 | 内置插件维护者 |
| `tests/` | 回归 | 所有功能开发者 |
| `docs/` | maintainer / developer 主线 | 文档维护者 |
| `config/` | 示例与部署模板 | 运维 / 平台 |
| `data/` | 运行时数据（不入库） | — |
| `local/plugins/` | 站点私有插件（不入库） | 运维 / 私有作者 |

## 易混边界

| 主题 | 源码 | 运行产物 / 其它 |
| --- | --- | --- |
| WebUI | `Pallas-Bot-WebUI` | `data/pb_webui/public/` |
| AI 执行 | `Pallas-Bot-AI` | 主仓定义产品与编排边界 |
| 官方玩法 | 对应扩展仓 | 主仓 `packages/` 未必有源码 |
| 文档主线 | `docs/maintainer/`、`docs/developer/` | 架构入口在 `docs/developer/architecture/` |

## 改动落点

1. 主仓还是兄弟仓？
2. 内核还是插件？
3. 源码还是运行产物？
4. 运维文档还是开发文档？

## 相关

- [架构总览](/developer/architecture/overview)
- [Core 与扩展](/developer/architecture/core-vs-extensions)
- [Platform API](platform-api.md)
