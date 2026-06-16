# 口令与功能

群里发下面任意一句（或 @ 牛），即可触发。  
**最全列表**以 **牛牛帮助** 返回的图为准（会标「何人可用」）。

::: tip 权限三字
| 词 | 意思 |
| --- | --- |
| 超管 | `pallas.toml` 里 `superusers` 的 QQ |
| 号主 | 该牛管理员列表里的 QQ |
| 群管 | QQ 群管理员 |
:::

---

## 开箱就有（core）

| 你发 | 牛会 |
| --- | --- |
| `牛牛帮助` | 发帮助图，群管可关单群插件 |
| `牛牛` | 打招呼（多牛同群可能齐回） |
| `牛牛喝酒` / `醒一醒` | 喝酒玩法 |
| `牛牛轮盘` | 轮盘；`牛牛救一下` / `牛牛补一枪` |
| 复读相关 | 学习群友说话后接话（见 [repeater](../plugins/repeater/README.md)） |

---

## 要先装官方扩展

| 你发 | 要先装 |
| --- | --- |
| 决斗、八角笼 | `plugins-duel` → [决斗](../plugins/duel/README.md) |
| 谁是卧底 | `plugins-who-is-spy` |
| `牛牛做梦` | `plugins-dream` |
| MAA 远控口令 | `plugins-maa` → [maa](../plugins/maa/README.md) |

安装步骤：[安装插件](install-plugins.md)。

---

## 要另起 AI 服务

| 你发 | 需要 |
| --- | --- |
| `牛牛唱歌` / 点歌 | [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) + 扩展包 |
| `牛牛画画` | 同上 + draw 扩展 |
| 随时 @ 闲聊 | 控制台打开 LLM；见 [AI 扩展](ai.md) |

可先发 `牛牛连通` 检查 Bot 能不能连上 AI。

---

## 管理向（网页操作）

| 目的 | 去哪 |
| --- | --- |
| 改配置 | `http://<主机>:8088/pallas/` |
| 扫码上 QQ | `/protocol/console/` |
| 关插件（全实例） | 控制台 **插件目录** 开关 |

详见 [网页控制台](web-console.md)。

---

▶ [插件手册](../plugins/README.md) · [使用指南（管理员）](../user/README.md)
