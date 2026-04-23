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

![learning-repeater](https://img.shields.io/badge/Feature-%E5%AD%A6%E4%B9%A0%E5%9E%8B%E5%A4%8D%E8%AF%BB-8A2BE2)
![plugin-system](https://img.shields.io/badge/Feature-%E6%8F%92%E4%BB%B6%E5%8C%96-00A3FF)
[![ai-chat-sing-tts](https://img.shields.io/badge/AI-Chat%26Sing%26TTS-6A5ACD)](https://github.com/PallasBot/Pallas-Bot-AI.git)
![database](https://img.shields.io/badge/Database-MongoDB%20%7C%20PostgreSQL-4EA94B)

[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-开发者群-red?style=logo=tencent-qq)](https://jq.qq.com/?_wv=1027&k=tlLDuWzc)
[![tencent-qq](https://img.shields.io/badge/%E7%BE%A4-拉牛牛群-c73e7e?style=logo=tencent-qq)](#qq-群)

</div>

> 面向群聊场景的学习型机器人：会复读、会整活、可管理、可扩展。  
> 🚀 当前主线：**Pallas-Bot 3.0**  
> 仍希望沿用 MongoDB-only 的老版本？完全兼容的 2.0 代码保留在 [`archive/v2`](https://github.com/PallasBot/Pallas-Bot/tree/archive/v2) 分支。  
> 从旧版本迁移到 `PG`：使用项目提供的 [Mongo -> PG 迁移脚本](tools/migrate_mongo_to_pg.py)。    
> 查看主线更新明细：[`版本更新`](#版本更新)

## 目录

- [关于项目](#关于项目)
  - [项目特点](#项目特点)
- [快速开始（部署）](#快速开始部署)
  - [部署方式](#部署方式)
  - [环境要求](#环境要求)
  - [简单部署](#简单部署)
- [使用指南](#使用指南)
  - [功能列表](#功能列表)
  - [AI 扩展](#ai-扩展)
- [配置与后端](#配置与后端)
- [版本更新](#版本更新)
- [常见问题（FAQ）](#常见问题faq)
- [开发与贡献指南](#开发与贡献指南)
- [社区与支持](#社区与支持)
  - [QQ 群](#qq-群)
  - [打赏](#打赏)
- [致谢](#致谢)
- [许可证](#许可证)

## 关于项目

牛牛的功能就是废话和复读。  
它以群聊语料学习为核心，结合娱乐玩法、管理能力和可选 AI 扩展，做最没用的牛牛！

### 项目特点

- 学习型复读，不依赖硬编码问答库
- 支持跨群语料聚合与全局禁用
- 玩法完整：喝酒、轮盘、唱歌、聊天、夺舍
- 管理能力：黑名单、好友欢迎、好友/入群申请管理
- 数据后端支持 `MongoDB` 与 `PostgreSQL`


## 快速开始（部署）

### 部署方式

- **托管实例接入**：加入 [`拉牛牛群`](#qq-群) 获取可用实例
- **标准部署（推荐）**：按 [部署教程](docs/Deployment.md) 执行完整流程
- **容器化部署**：使用 [Docker 部署](docs/DockerDeployment.md)

### 环境要求

- `Python 3.12+`
- `uv`
- `MongoDB` 或 `PostgreSQL`（二选一）
- `OneBot v11` 协议端

### 简单部署

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
> 部署好自己牛牛之后，如果托管别人的账号成为你的牛牛，别忘记将他设置为牛牛的管理员!号主们都应该有控制自己牛牛的权力。

## 使用指南

### 功能列表

<details>
  <summary>展开查看完整功能列表</summary>

#### 基础功能

- `help`:牛牛帮助，查看牛牛可用插件以及开关状态
- `repeater`：牛牛复读的核心组件
- `drink`:牛牛喝酒，控制牛牛醉酒与醒酒状态，并影响聊天/轮盘行为概率。
- `roulette`:牛牛轮盘，提供踢人/禁言轮盘玩法，支持“救一下”“补一枪”。
- `greeting`:牛牛群欢迎，处理入群/好友欢迎和部分群通知，支持自定义欢迎消息。
- `take_name`:自动夺舍，定时同步或随机更换牛牛群名片。
- `chat`:酒后聊天，牛牛醉酒时启用 AI 对话能力，支持 @牛牛 或“牛牛 + 文本”触发。（依赖 AI 服务端）。
- `sing`:牛牛唱歌，提供 AI 唱歌、继续唱、点歌与歌曲查询能力（依赖 AI 服务端）。
#### 群管理员功能

- `help`:牛牛帮助，管理员可以查看帮助并管理功能开关（按功能名/序号启用或禁用）。
- `roulette`:牛牛轮盘，管理员可以通过牛牛轮盘禁言/踢人控制玩法，支持“救一下”“补一枪”。
#### 牛牛管理员可用功能

- `greeting`:牛牛群欢迎，自定义牛牛添加好友的欢迎消息。
- `request_handler`:申请管理，管理好友申请与入群邀请，支持审批与自动同意开关。
#### 超管可用功能

- `bot_status`:牛牛状态查询，查询在线/离线 bot 状态并支持离线通知（含测试邮件）。
- `help`:牛牛帮助，超管可以查看并管理隐藏的功能（按功能名/序号启用或禁用）。
- `bot_status`:牛牛在吗，查询在线/离线 bot 并支持离线通知（含测试邮件）。
</details>

### AI 扩展

部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 并开启对应能力后可用：

- `牛牛唱歌 <网易云歌曲 ID 或 歌名>`（指定翻唱）`牛牛唱歌`（播放唱过的歌曲）
- `牛牛点歌 <网易云歌曲 ID 或 歌名>`
- `网易云登录` / `网易云登出`
- 酒后聊天（ChatRWKV 模型）
- 文本转语音（TTS）

## 配置与后端

以下为常用配置项，完整说明请以 `.env` 文件注释为准：


| 配置项               | 默认/示例                               | 说明                    | 必填      |
| ----------------- | ----------------------------------- | --------------------- | ------- |
| `DB_BACKEND`      | `mongo` / `postgres`                | 选择数据后端                | 是       |
| `PG_POOL_SIZE`    | `10`                                | PostgreSQL 连接池基础连接数   | 否（仅 PG） |
| `PG_MAX_OVERFLOW` | `20`                                | PostgreSQL 连接池最大额外连接数 | 否（仅 PG） |
| `PG_POOL_RECYCLE` | `1800`                              | PostgreSQL 连接回收时间（秒）  | 否（仅 PG） |
| `OneBot WS URL`   | `ws://localhost:8088/onebot/v11/ws` | 协议端连接地址               | 是       |


## 版本更新

当前主线（`3.0`）简要更新：

- 数据层：新增 `PostgreSQL` 后端并支持 `Mongo -> PG` 迁移
- 插件体验：优化 `repeater`、重构并修复 `roulette`、新增 `drink` 醒酒能力
- 稳定性：修复 `Bot` 关闭时的 `RuntimeError`
- 工程化：引入 `AGENTS.md` 与 `pre-commit` 规范

更多版本详情请查看 [Releases](https://github.com/PallasBot/Pallas-Bot/releases)。

## 常见问题（FAQ）

[`FAQ`](docs/FAQ.md)

快速入口：

- [`学习机制`](docs/FAQ.md#学习机制)：跨群语料、训练方式
- [`使用与管理`](docs/FAQ.md#使用与管理)：不当发言处理、主动发言机制
- [`部署排障`](docs/FAQ.md#部署排障)：启动后不回复的优先排查顺序

如果你是第一次部署，建议阅读顺序：
[`快速开始（部署）`](#快速开始部署) -> [`首次启动自检`](#首次启动自检) -> [`部署排障`](docs/FAQ.md#部署排障)

## 开发与贡献指南

欢迎通过 [Issues](https://github.com/PallasBot/Pallas-Bot/issues) / PR 参与改进。  
查看我们的 [`贡献指南`](CONTRIBUTING.md)以了解如何参与贡献。


## 社区与支持

### QQ 群

- 开发者
  - 开发者群：`716692626`

- 拉牛牛
  - 牢牛今天寄了吗：`789311420`
  - 西海福牛养殖基地：`372948792`
  - 牛牛工坊：`1043301356`

- 闲聊
  - 帕拉斯工坊：`566968684`
  - 帕拉斯の工坊：`865638357`
  - 西海福牛养殖学院：`733291779`
  - 丽丽玛玛玛：`926623539`

### 打赏

请作者喝杯咖啡吧（请备注牛牛项目，感谢你的支持 ✿✿ヽ(°▽°)ノ✿）：

## 致谢

- [`NoneBot2`](https://github.com/nonebot/nonebot2)
- [`jieba_next`](https://github.com/mxcoras/jieba-next)
- [`beanie`](https://github.com/BeanieODM/beanie)
- [`NapCat`](https://github.com/NapNeko/NapCatQQ)

## 许可证

本项目采用 `GNU Affero General Public License v3.0`（AGPL-3.0）许可证，详见 [LICENSE](LICENSE)。