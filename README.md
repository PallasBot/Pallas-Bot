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

> 🚀 当前主线：**Pallas-Bot 3.0**  
> 仍希望沿用 MongoDB-only 的老版本？完全兼容的 2.0 代码保留在 [`archive/v2`](https://github.com/PallasBot/Pallas-Bot/tree/archive/v2) 分支。  
> 从旧版本迁移到 `PG`：使用项目提供的 [Mongo -> PG 迁移脚本](tools/migrate_mongo_to_pg.py)。  
> 面向群聊场景的学习型机器人：会复读、会整活、可管理、可扩展。  
> 查看主线更新明细：[`版本更新（3.0）`](#版本更新30)

## 目录

- [关于项目](#关于项目)
  - [项目特点](#项目特点)
  - [技术栈](#技术栈)
- [快速开始（部署）](#快速开始部署)
  - [部署方式](#部署方式)
  - [环境要求](#环境要求)
  - [安装步骤](#安装步骤)
  - [最小运行要求](#最小运行要求)
  - [运行方式](#运行方式)
  - [首次启动自检](#首次启动自检)
- [使用指南](#使用指南)
  - [常用指令](#常用指令)
  - [AI 扩展能力可选](#ai-扩展能力可选)
- [配置与后端](#配置与后端)
- [版本更新（3.0）](#版本更新30)
- [常见问题（FAQ）](#常见问题faq)
  - [FAQ 文档](docs/FAQ.md)
- [开发与贡献指南](#开发与贡献指南)
- [社区与支持](#社区与支持)
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

### 技术栈

- Bot Framework: [`NoneBot2`](https://github.com/nonebot/nonebot2)
- Adapter/Protocol: `OneBot v11`（`NapCat` / `Lagrange.OneBot` / `AstralGocq`）
- Database: `MongoDB` / `PostgreSQL`
- Runtime: `Python 3.12+`
- Dependency Manager: `uv`

## 快速开始（部署）

### 部署方式

- **托管实例接入**：加入 [`拉牛牛` QQ 群](#qq-群) 获取可用实例
- **标准部署（推荐）**：按 [部署教程](docs/Deployment.md) 执行完整流程
- **容器化部署**：使用 [Docker 部署](docs/DockerDeployment.md)
- **最小可运行验证**：按本节最小运行要求与运行方式启动

### 环境要求

- `Python 3.12+`
- `uv`
- `MongoDB` 或 `PostgreSQL`（二选一）
- `OneBot v11` 协议端

### 安装步骤

```bash
git clone https://github.com/PallasBot/Pallas-Bot.git
cd Pallas-Bot
uv sync
```

### 最小运行要求

首次启动至少确保下面 3 项成立：

1. 已在 `.env` 中选择数据后端（`DB_BACKEND=mongo` 或 `DB_BACKEND=postgres`）
2. 数据库服务可连接（本机默认地址或你自定义地址）
3. `OneBot v11` 协议端已启动，并连接到：
  - `ws://localhost:8088/onebot/v11/ws`

### 运行方式

1. 根据仓库根目录 `.env` 注释按需配置
2. 启动 `OneBot v11` 协议端，`WebSocket URL` 指向：
  - `ws://localhost:8088/onebot/v11/ws`
3. 启动 Bot：

```bash
uv run nb run
```

### 首次启动自检

启动后可用以下方式快速确认是否部署成功：

- 控制台无持续报错，Bot 进程保持运行
- 在群聊发送 `牛牛帮助` 能收到回复
- 在群聊发送 `牛牛在吗`（超管）可看到在线状态

若失败，请检查：数据库连通性、`OneBot WS` 地址、`.env` 配置是否生效。

> 完整部署细节请查看 [部署教程](docs/Deployment.md) 和 [Docker 部署](docs/DockerDeployment.md)。

## 使用指南

### 常用指令

- `牛牛帮助`：查看所有功能并控制功能的开关
- `牛牛喝酒` / `牛牛醒一醒` / `牛牛别喝了`
- `牛牛轮盘` / `牛牛开枪`
- `牛牛救一下` / `牛牛补一枪`（可 @ 用户）
- `设置好友欢迎` / `清除好友欢迎`
- `牛牛在吗`（仅超管，详见 [`bot_status`](src/plugins/bot_status/README.md)）

### AI 扩展能力（可选）

部署 [Pallas-Bot-AI](https://github.com/PallasBot/Pallas-Bot-AI) 并开启对应能力后可用：

- `牛牛唱歌 <网易云歌曲 ID 或 歌名>`
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


## 版本更新（3.0）

### 数据层

1. 新增 `PostgreSQL` 后端，`DB_BACKEND` 一键切换（`c334a07`）
2. 提供 [`Mongo -> PG` 迁移脚本](tools/migrate_mongo_to_pg.py)（流式迁移、断点续传、脏数据容错）（`c334a07`）
3. 高频写入原子化（`ON CONFLICT`）降低计数丢失风险（`c334a07`）
4. 主键 `BigInt` 化与索引优化，支持千万级长期累积（`c334a07`）
5. 连接池参数化与缓存优化，提高高 QPS 稳定性（`c334a07`）

### 插件与体验

1. `repeater` 优化 `speaker` 消息选择策略，减少重复回复（`0419297`）
2. `roulette` 重构：合并“救一下 / 补一枪”能力，修复玩家状态管理并拆分插件结构（`d275b0c`、`8763d2f`）
3. `roulette` 修复“补一枪后无法救一下”问题，并同步优化相关配置（`1110b77`、`c30e8b4`）
4. `drink` 新增醒酒功能：`牛牛醒一醒` / `牛牛别喝了`（`8f30106`）
5. 全部插件版本号升级至 `3.0.0`（`b85b1a8`）

### Bug 修复

1. 修复 `Bot` 关闭时异常的 `RuntimeError`（`20d5535`）

### 工程化

1. 增加 `AGENTS.md` 协作约定，并引入 `pre-commit` 配置以统一本地检查流程（`4d5ec98`）

## 常见问题（FAQ）

完整 FAQ 已迁移到独立文档：[`docs/FAQ.md`](docs/FAQ.md)。

高频问题快速入口：

- [`学习机制`](docs/FAQ.md#学习机制)：跨群语料、训练方式
- [`使用与管理`](docs/FAQ.md#使用与管理)：不当发言处理、主动发言机制
- [`部署排障`](docs/FAQ.md#部署排障)：启动后不回复的优先排查顺序

如果你是第一次部署，建议阅读顺序：
[`快速开始（部署）`](#快速开始部署) -> [`首次启动自检`](#首次启动自检) -> [`部署排障`](docs/FAQ.md#部署排障)

## 开发与贡献指南

### 本地开发

```bash
uv sync --dev
uv run ruff check src/
uv run ruff format --check src/
```

自动修复：

```bash
uv run ruff check --fix src/
uv run ruff format src/
```

运行测试（如仓库包含测试）：

```bash
uv run pytest
```

欢迎通过 Issue / PR 参与改进。

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