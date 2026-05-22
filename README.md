<div align="center">
  <img alt="LOGO" src="https://user-images.githubusercontent.com/18511905/195892994-c1a231ec-147a-4f98-ba75-137d89578247.png" width="360" height="270" />
  <h1>Pallas-Bot</h1>

  <p>我是来自米诺斯的祭司帕拉斯，会在罗德岛休息一段时间......</p>
  <p>虽然这么说，我渴望以美酒和戏剧被招待，更渴望走向战场。</p>

  <p>
    <a href="https://github.com/PallasBot/Pallas-Bot/issues">报告 Bug</a> ·
    <a href="https://github.com/PallasBot/Pallas-Bot/issues">提出新特性</a> ·
    <a href="docs/Deployment.md">快速部署</a>
  </p>

</div>


<div align="center">

[![license](https://img.shields.io/badge/license-AGPL3.0-FE7D37)](./LICENSE)
[![python](https://img.shields.io/badge/Python-3.12%2B-blue)](https://www.python.org)
[![nonebot2](https://img.shields.io/badge/nonebot2-%3E%3D2.4.4-EA5252)](https://nonebot.dev/)
[![onebot](https://img.shields.io/badge/OneBot-v11-black?style=social&logo=data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABABAMAAABYR2ztAAAAIVBMVEUAAAAAAAADAwMHBwceHh4UFBQNDQ0ZGRkoKCgvLy8iIiLWSdWYAAAAAXRSTlMAQObYZgAAAQVJREFUSMftlM0RgjAQhV+0ATYK6i1Xb+iMd0qgBEqgBEuwBOxU2QDKsjvojQPvkJ/ZL5sXkgWrFirK4MibYUdE3OR2nEpuKz1/q8CdNxNQgthZCXYVLjyoDQftaKuniHHWRnPh2GCUetR2/9HsMAXyUT4/3UHwtQT2AggSCGKeSAsFnxBIOuAggdh3AKTL7pDuCyABcMb0aQP7aM4AnAbc/wHwA5D2wDHTTe56gIIOUA/4YYV2e1sg713PXdZJAuncdZMAGkAukU9OAn40O849+0ornPwT93rphWF0mgAbauUrEOthlX8Zu7P5A6kZyKCJy75hhw1Mgr9RAUvX7A3csGqZegEdniCx30c3agAAAABJRU5ErkJggg==)](https://onebot.dev/)
[![stars](https://img.shields.io/github/stars/PallasBot/Pallas-Bot?style=social)](https://github.com/PallasBot/Pallas-Bot/stargazers)
[![ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

[![maa-remote](https://img.shields.io/badge/Feature-MAA%20%E8%BF%9C%E6%8E%A7-FE7D37)](docs/plugins/maa/README.md)
![learning-repeater](https://img.shields.io/badge/Feature-%E5%AD%A6%E4%B9%A0%E5%9E%8B%E5%A4%8D%E8%AF%BB-8A2BE2)
![plugin-system](https://img.shields.io/badge/Feature-%E6%8F%92%E4%BB%B6%E5%8C%96-00A3FF)
[![ai-chat-sing-tts](https://img.shields.io/badge/AI-Chat%26Sing%26TTS-6A5ACD)](https://github.com/PallasBot/Pallas-Bot-AI.git)
![database](https://img.shields.io/badge/Database-MongoDB%20%7C%20PostgreSQL-4EA94B)

[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-开发者群-red?style=logo=tencent-qq)](https://jq.qq.com/?_wv=1027&k=tlLDuWzc)
[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-拉牛牛-c73e7e?style=logo=tencent-qq)](#qq-群)

</div>

<p align="center">面向群聊场景的学习型机器人：会复读、会整活、可管理、可扩展。</p>
<p align="center">亦可作为 <b>MAA（MaaAssistantArknights）</b> 的 QQ 侧远控：绑定设备后，在群聊或私聊用口令排队任务。</p>

>牛牛 基于 **`NoneBot2`** 与 **`OneBot v11`**，数据层支持 **`MongoDB`** 或 **`PostgreSQL`**；自带运维面板 [**`Pallas-Bot-WebUI`**](https://github.com/PallasBot/Pallas-Bot-WebUI.git)。使用 MAA 远控时，牛牛实现 [MAA 远程控制协议](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)（详见 [MAA 远控](#maa-远控)）。
发版与变更说明见 [Releases](https://github.com/PallasBot/Pallas-Bot/releases)；若需参考仅 **`MongoDB`** 的历史实现，见分支 [`archive/v2`](https://github.com/PallasBot/Pallas-Bot/tree/archive/v2)；向 **`PostgreSQL`** 迁移可使用 [Mongo → PG 迁移脚本](tools/migrate_mongo_to_pg.py)。

<!-- Copy-paste in your Readme.md file -->

<a href="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history?repo_id=425810267" target="_blank" style="display: block" align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=dark" width="721" height="auto">
    <img alt="Star History of PallasBot/Pallas-Bot" src="https://next.ossinsight.io/widgets/official/analyze-repo-stars-history/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=light" width="721" height="auto">
  </picture>
</a>

<!-- Made with [OSS Insight](https://ossinsight.io/) -->
>喜欢牛牛，就给牛牛点个 [**⭐**](https://github.com/PallasBot/Pallas-Bot/stargazers) 吧！

## 📑 目录

- [关于项目](#关于项目)
  - [项目特点](#项目特点)
  - [MAA 远控](#maa-远控)
- [运维入口](#运维入口)
- [快速开始（部署）](#快速开始部署)
  - [部署方式](#部署方式)
  - [环境要求](#环境要求)
  - [简单部署](#简单部署)
- [使用指南](#使用指南)
  - [功能列表](#功能列表)
  - [AI 扩展](#ai-扩展)
- [配置要点](#配置要点)
- [文档与链接](#文档与链接)
- [开发与贡献指南](#开发与贡献指南)
- [社区与支持](#社区与支持)
  - [QQ 群](#qq-群)
  - [打赏](#打赏)
- [致谢](#致谢)
- [许可证](#许可证)

<a id="关于项目"></a>
## 📖 关于项目

牛牛的功能就是废话和复读。可以认为是高级版的复读机。
发现牛牛学了一些不合适的话及时帮忙[删除](docs/FAQ.md#使用与管理)。
大家一起教出更棒更聪明的牛牛！✿✿ヽ(°▽°)ノ✿

若你使用 [**MaaAssistantArknights**](https://github.com/MaaAssistantArknights/MaaAssistantArknights)，牛牛还可作为其 QQ 侧远控：在 MAA 中配置远控地址并私聊绑定设备后，用「牛牛长草」「牛牛作战」等口令排队任务，执行结果与截图会回到 QQ（说明见下文 [MAA 远控](#maa-远控)）。

<a id="项目特点"></a>
### ✨ 项目特点

- 学习型复读，不依赖硬编码问答库
- 支持跨群语料聚合与全局禁用
- 牛牛玩法：喝酒、轮盘、决斗、做梦、唱歌、聊天、生图、夺舍等；
- 管理能力：黑名单、好友欢迎、好友/入群申请管理
- 数据后端：`MongoDB` 或 `PostgreSQL`
- 运维：`pallas_webui` 控制台、`pallas_protocol` 协议端管理
- **MAA 远控**（可选）：与 MAA 客户端配合，在 QQ 绑定设备、下发口令、回传截图与状态（详见 [MAA 远控](#maa-远控)）
- **牛牛帮助**：三级帮助图（总览 → 插件 → 功能详情）；群管可按插件开关功能
- **牛牛连通**：探测画画网关、MAA 端点、唱歌 AI 等延迟（WebUI 可一键检测）

<a id="maa-远控"></a>
### 📡 MAA 远控

与 [**MaaAssistantArknights**](https://github.com/MaaAssistantArknights/MaaAssistantArknights) 配套：MAA 在本地跑任务，牛牛在 QQ 侧**绑定设备、排队口令、回传截图与状态**（`getTask` / `reportStatus`）。

1. 配置 `maa_public_base_url`（见 [maa 插件说明](docs/plugins/maa/README.md)）
2. MAA「设置 → 远程控制」填入帮助页 URL，用户标识符填 QQ 号
3. 私聊 `牛牛绑定MAA <设备标识符>`，群聊发 `牛牛长草`、`牛牛作战` 等

口令一览、多设备与排障见 [docs/plugins/maa/README.md](docs/plugins/maa/README.md) 或 **牛牛帮助 → MAA 远控**；协议见 [MAA 远程控制文档](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)。

<a id="运维入口"></a>
## 🗂️ 运维入口

以下路径中的 **`HOST`**、**`PORT`** 以 `.env` 为准（默认常为本机 **`8088`**）。

| 入口 | URL 示例 |
| --- | --- |
| Web 控制台 | `http://<HOST>:<PORT>/pallas/` |
| 协议端管理 | `http://<HOST>:<PORT>/protocol/console/` |

- **登录口令**：控制台与协议端管理**共用**；首次启动见 Bot 日志。遗忘后的处理见 [FAQ · 部署排障](docs/FAQ.md#部署排障)。
- **Docker**：`pallasbot` 服务镜像见根目录 [`docker-compose.yml`](docker-compose.yml) 的 `image`；需对齐某次 Release 时请直接改为带 tag 的镜像名（或自建 override 文件）。
- **排障与插件字段**：[FAQ](docs/FAQ.md)、[协议端（pallas_protocol）](docs/plugins/pallas_protocol/README.md)、[控制台（pallas_webui）](docs/plugins/pallas_webui/README.md)。

<a id="快速开始部署"></a>
## 🚀 快速开始（部署）

<a id="部署方式"></a>
### 📦 部署方式

- **托管实例接入**：加入 [拉牛牛群](#qq-群) 获取可用实例
- **标准部署**：按 [部署教程](docs/Deployment.md) 执行完整流程
- **容器化部署**：使用 [Docker 部署](docs/DockerDeployment.md)

<a id="环境要求"></a>
### 📋 环境要求

- `Python 3.12+`
- `uv`
- `MongoDB` 或 `PostgreSQL`（二选一）
- `OneBot v11` 协议端

<a id="简单部署"></a>
### ⚡ 简单部署

```bash
#获取代码
git clone https://github.com/PallasBot/Pallas-Bot.git

#进入目录
cd Pallas-Bot

# 安装依赖
pip install uv          # 安装 uv
uv sync                 # 安装依赖

# 开始运行
uv run nb run
```
> 完整部署细节请查看 [部署教程](docs/Deployment.md) 和 [Docker 部署](docs/DockerDeployment.md)。
> 部署好自己牛牛之后，若将他人账号接为自己的牛牛，请把对方 QQ 写入该牛牛的 **`admins`**（号主）；**新建牛牛**时也可由超管私聊 **「创建牛牛」** 并在命令里带上号主 QQ，**会自动写入** `admins`。详见 [FAQ：如何为牛牛配置号主（`admins`）](docs/FAQ.md#faq-bot-admins)。

<a id="使用指南"></a>
## 📚 使用指南

<a id="功能列表"></a>
### 🎮 功能列表

<details>
  <summary>忘记了就用牛牛帮助!</summary>

#### MAA 远控（[`maa`](docs/plugins/maa/README.md)）

| 类型 | 口令示例 |
| --- | --- |
| 绑定 / 设备 | `牛牛绑定MAA`、`牛牛MAA状态`、`牛牛切换MAA设备`、`牛牛MAA设备名`、`牛牛清空MAA队列` |
| 任务 | `牛牛长草`、`牛牛作战`、`牛牛公招`、`牛牛基建`、`牛牛截图`、`牛牛停止` 等 |
| 高级 | `牛牛MAA任务 <type> [params]`（协议原始 type） |

#### 基础玩法

| 口令 / 插件 | 说明 |
| --- | --- |
| `牛牛帮助` | 三级帮助图：总览 → 插件 → 功能；`牛牛开启` / `牛牛关闭` 管理本群插件 |
| `牛牛喝酒` / `牛牛醒一醒` | 醉酒与醒酒，影响聊天、轮盘、夺舍、做梦等 |
| `牛牛轮盘` | 踢人/禁言轮盘；`牛牛救一下`、`牛牛补一枪` |
| `牛牛决斗` / `八角笼牛` | 泰拉风味多幕决斗、干员 QTE、双牛八角笼（[duel](docs/plugins/duel/README.md)） |
| `牛牛做梦` / `牛牛醒梦` | 跨群梦话漂流、历史梦与画画归档图；醉酒联动夺舍（[dream](docs/plugins/dream/README.md)） |
| 酒后聊天 | 醉酒时 @牛牛 或「牛牛 + 文本」（依赖 [AI 服务](https://github.com/PallasBot/Pallas-Bot-AI)） |
| `牛牛唱歌` | 翻唱、继续唱、点歌、查歌名（依赖 AI 服务） |
| `牛牛画画` | AI 生图，可附图或回复图作参考 |
| `牛牛连通` / `牛牛网关` | 探测画画、MAA、唱歌等服务延迟（[connectivity](docs/plugins/connectivity/README.md)） |

#### 被动与管理

- **复读**（`repeater`）：学习型复读核心
- **欢迎**（`greeting`）：入群/好友欢迎与部分群通知
- **夺舍**（`take_name`）：定时改牛牛群名片；醉酒时可能同步改群友名片
- **控制台**（`pallas_webui`）、**协议端**（`pallas_protocol`）：Web 运维与多账号协议端
- **群管**：帮助与插件开关；轮盘禁言/踢人需群管权限
- **号主**（`admins`）：`牛牛重新上号`、`设置好友欢迎`、`同意好友/入群`、`牛牛在吗`
- **超管**：`创建牛牛`、隐藏功能开关、`牛牛在吗`（含邮件测试）
</details>

<a id="ai-扩展"></a>
### 🤖 AI 扩展

部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 并开启对应能力后可用：
<details>
  <summary>展开查看完整功能列表</summary>

- `[角色名]唱歌 <歌曲名>`（指定翻唱，支持 `key=N` 调整音调）& `[角色名]唱歌`（播放唱过的歌曲）
- `[角色名]继续唱` / `[角色名]接着唱`（继续上次未完成的歌曲）
- `[角色名]什么歌` / `[角色名]哪首歌`（查询当前播放歌曲名）
- `牛牛点歌 <歌曲名>`
- `网易云登录` / `网易云登出`
- 酒后聊天（ChatRWKV 模型）
- 酒后聊天内容文本转语音（TTS）

</details>

<a id="配置要点"></a>
## ⚙️ 配置要点

以下为启动前最常见的几项；**更多键名与默认值以各插件 Pydantic 配置为准**，推荐在 Web 控制台 **「插件」「通用配置」** 中修改（写入 `data/pallas_config/webui.json`），离线编辑主配置见 `config/pallas.example.toml` → `config/pallas.toml`，说明见 [配置存储](docs/architecture/settings-storage.md)。


| 配置项 | 默认/示例 | 说明 | 必填 |
| --- | --- | --- | --- |
| `HOST` / `PORT` | `0.0.0.0` / `8088` | Bot HTTP 监听；控制台与协议管理页同源 | 是 |
| `SUPERUSERS` | QQ 号列表 | 超管 QQ | 是 |
| `DB_BACKEND` | `mongodb` / `postgresql` | 数据后端 | 是 |
| `MONGO_*` / `PG_*` | 见 `config/pallas.example.toml` | 数据库地址与账号（与 `DB_BACKEND` 对应） | 是 |
| `ACCESS_TOKEN` | 空 | 驱动层 HTTP 鉴权；公网暴露时建议填写 | 否 |
| `PALLAS_PROTOCOL_ENABLED` / `PALLAS_PROTOCOL_WEBUI_ENABLED` | 默认开启 | 协议端插件与管理页 | 否 |
| `maa_public_base_url` | （空） | MAA 远控对外 HTTP 基址；一般部署**只需此项**（见 [maa](docs/plugins/maa/README.md)） | 使用 MAA 时建议填 |


控制台与协议管理页为**浏览器登录**，口令在 `data/pallas_console/`；说明见 [pallas_webui](docs/plugins/pallas_webui/README.md)、[pallas_protocol](docs/plugins/pallas_protocol/README.md)，遗忘与排障见 [FAQ](docs/FAQ.md)。

<a id="文档与链接"></a>
## 📚 文档与链接

| 类型 | 链接 |
| --- | --- |
| 标准部署 | [docs/Deployment.md](docs/Deployment.md) |
| Docker | [docs/DockerDeployment.md](docs/DockerDeployment.md) |
| 常见问题 | [docs/FAQ.md](docs/FAQ.md)（[学习机制](docs/FAQ.md#学习机制)、[使用与管理](docs/FAQ.md#使用与管理)、[部署排障](docs/FAQ.md#部署排障)） |
| 插件索引 | [docs/plugins/README.md](docs/plugins/README.md) |
| MAA 远控 | [docs/plugins/maa/README.md](docs/plugins/maa/README.md) |
| 连通性检测 | [docs/plugins/connectivity/README.md](docs/plugins/connectivity/README.md) |
| 命令权限 / 帮助菜单 | [docs/common/cmd_perm/README.md](docs/common/cmd_perm/README.md) |
| 协议端 / 控制台 | [pallas_protocol](docs/plugins/pallas_protocol/README.md)、[pallas_webui](docs/plugins/pallas_webui/README.md) |
| 变更记录 | [GitHub Releases](https://github.com/PallasBot/Pallas-Bot/releases) |
| 数据迁移 | [Mongo → PG 脚本](tools/migrate_mongo_to_pg.py)、[迁移说明（v3）](docs/Migration-v3.md) |
| 历史分支 | [`archive/v2`](https://github.com/PallasBot/Pallas-Bot/tree/archive/v2)（仅 MongoDB 旧版参考） |

<a id="开发与贡献指南"></a>
## 💻 开发与贡献指南

欢迎通过 [Issues](https://github.com/PallasBot/Pallas-Bot/issues) / PR 参与改进。参与前请阅读 [贡献指南](CONTRIBUTING.md) 与仓库根目录 [AGENTS.md](AGENTS.md)（本地安装、Ruff、pytest、提交约定）。


<a id="社区与支持"></a>
## 🤝 社区与支持

<a id="qq-群"></a>
### 💬 QQ 群

- #### 开发者
  - [`牛牛听话!`](https://qm.qq.com/q/yIiAajYwms)
- #### 拉牛牛
  - [`牢牛今天寄了吗`](https://qun.qq.com/universal-share/share?ac=1&authKey=ED2GgLVICB%2F%2BCVuZKtMrOFBr%2F8foYDU2DE80dFji9gvwaTb0GNitvZv2c8ifkLfR&busi_data=eyJncm91cENvZGUiOiI3ODkzMTE0MjAiLCJ0b2tlbiI6IlFZN2EyanJuSGEwR3Exb0RWNjYxSldLT3hPWSt2V0o5QVhqYktHNnVyZFlQbFJ2MlNIcDlpNC9zRVk0TS83TWIiLCJ1aW4iOiIzNDE1NzUwMTc4In0%3D&data=KMV9QtwR8GD1IJe2iba5hugcJCZcWsmv9vGhWZEnOIp0wHpnE7k7fVBKxJHgbYs7Ym4xKuar30OLIqVFySDPmA&svctype=4&tempid=h5_group_info)
  - [`西海福牛养殖基地`](https://qm.qq.com/q/5GjZ2xHeb6)
  - [`牛牛工坊`](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=snSe5PkcmHZrD0OA5Wzl2RAnM-qoAMUc&authKey=T%2FQlcyy31oE7YyMDMd7Yys7utl5a9jP84VYgnknra8Knsq3BhEy5TrwiWK7rG8j6&noverify=0&group_code=1043301356)
- #### 闲聊
  - [`泛用型群聊解决方案0.1.0b1`](https://qm.qq.com/q/KEB1Z8kC4)
  - [`帕拉斯の工坊`](https://qm.qq.com/q/qP3hv0OfE6)
  - [`西海福牛养殖学院`](https://qm.qq.com/q/8P)
  - [`丽丽玛玛玛?`](https://qm.qq.com/q/Qgc6ir7Jk)

<a id="打赏"></a>
### 💝 打赏

请作者喝杯咖啡吧（请备注牛牛项目，感谢你的支持 ✿✿ヽ(°▽°)ノ✿）：

<a href="https://afdian.com/a/misteo">
  <img width="200" src="https://pic1.afdiancdn.com/static/img/welcome/button-sponsorme.png">
</a>

<a id="致谢"></a>
## 🙏 致谢

- [**MaaAssistantArknights**](https://github.com/MaaAssistantArknights/MaaAssistantArknights.git)：明日方舟长草助手 MAA ；本项目的远控能力基于其[远程控制协议](https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html)实现
- [**NoneBot2**](https://github.com/nonebot/nonebot2)：跨平台 Python 异步聊天机器人框架
- [**jieba_next**](https://github.com/mxcoras/jieba-next)：Use Rust to Speed up jieba 高效、现代的中文分词库
- [**beanie**](https://github.com/BeanieODM/beanie)：Asynchronous Python ODM for MongoDB
- [**NapCat**](https://github.com/NapNeko/NapCatQQ)：现代化的基于 NTQQ 的 Bot 协议端实现
- [**zhenxun_bot**](https://github.com/zhenxun-org/zhenxun_bot.git)：非常可爱的绪山真寻Bot
- [**Amiya-bot**](https://github.com/AmiyaBot/Amiya-Bot.git)：基于 AmiyaBot 框架的 QQ 聊天机器人
- [**CustomMarkdownImage**](https://github.com/Monody-S/CustomMarkdownImage.git)：基于pillow的可自定义markdown渲染器
## 📊 统计
<!-- Copy-paste in your Readme.md file -->

<a href="https://next.ossinsight.io/widgets/official/analyze-repo-pushes-and-commits-per-month?repo_id=425810267" target="_blank" style="display: block" align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://next.ossinsight.io/widgets/official/analyze-repo-pushes-and-commits-per-month/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=dark" width="721" height="auto">
    <img alt="Pushes and Commits of PallasBot/Pallas-Bot" src="https://next.ossinsight.io/widgets/official/analyze-repo-pushes-and-commits-per-month/thumbnail.png?repo_id=425810267&image_size=auto&color_scheme=light" width="721" height="auto">
  </picture>
</a>

<!-- Made with [OSS Insight](https://ossinsight.io/) -->
<!-- Copy-paste in your Readme.md file -->

<a href="https://next.ossinsight.io/widgets/official/compose-recent-active-contributors?repo_id=425810267&limit=30" target="_blank" style="display: block" align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://next.ossinsight.io/widgets/official/compose-recent-active-contributors/thumbnail.png?repo_id=425810267&limit=30&image_size=auto&color_scheme=dark" width="655" height="auto">
    <img alt="Active Contributors of PallasBot/Pallas-Bot - Last 28 days" src="https://next.ossinsight.io/widgets/official/compose-recent-active-contributors/thumbnail.png?repo_id=425810267&limit=30&image_size=auto&color_scheme=light" width="655" height="auto">
  </picture>
</a>

<!-- Made with [OSS Insight](https://ossinsight.io/) -->
## 👥 贡献者

感谢各位大佬！

[![Contributors](https://contributors-img.web.app/image?repo=PallasBot/Pallas-Bot)](https://github.com/PallasBot/Pallas-Bot/graphs/contributors)

<a id="许可证"></a>
## 📄 许可证

本项目采用 `GNU Affero General Public License v3.0`（AGPL-3.0）许可证，详见 [LICENSE](LICENSE)。
