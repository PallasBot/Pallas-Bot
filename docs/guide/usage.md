# 命令与功能

::: tip
群里发下列口令（或 @ 牛）即可触发。完整列表与「何人可用」以 **牛牛帮助** 帮助图为准。
:::

::: details 权限三个词
| 词 | 意思 |
| --- | --- |
| 超管 | `pallas.toml` 里 `superusers` |
| 号主 | 该牛 `admins` 列表里的 QQ；配置见 [号主](bot-owner.md) |
| 群管 | QQ 群管理员 |
:::

## 开箱即有

| 口令 | 作用 |
| --- | --- |
| `牛牛帮助` | 功能帮助图；群管可关单群插件 |
| `牛牛` | 打招呼（多牛同群可能齐回） |
| `牛牛喝酒` / `醒一醒` | 喝酒玩法 |
| `牛牛轮盘` | 轮盘；`牛牛救一下` / `牛牛补一枪` |
| （自然接话） | 学群友说话后复读接话 |

## 需安装官方插件

| 口令 | 插件包 |
| --- | --- |
| 决斗、八角笼 | `pallas-plugin-duel` |
| 谁是卧底 | `pallas-plugin-who-is-spy` |
| `牛牛做梦` | `pallas-plugin-dream` |
| MAA 远控 | `pallas-plugin-maa` |

安装步骤 → [安装插件](install-plugins.md)

## 需 Pallas-Bot-AI

| 口令 | 依赖 |
| --- | --- |
| `牛牛唱歌` / `牛牛点歌` | [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) + `pallas-plugin-ai-media` |
| `牛牛画画` | 同上 + `pallas-plugin-draw` |
| @ 牛闲聊 | 控制台打开 `LLM_CHAT_ENABLED`；见 [AI 扩展](ai.md) |

连通性测试：群里发 `牛牛连通`。

## 控制台入口

| 任务 | 地址 / 侧栏 |
| --- | --- |
| 改配置 | `http://<主机>:8088/pallas/` |
| 扫码上 QQ | `/pallas/protocol` |
| 关插件 | 控制台 **插件** |

面板说明 → [网页控制台](web-console.md)
