# 语料联邦

管理牛牛**接话素材从哪来**：默认只用**本机库**；可选接入**社区共享池**读写匿名短句。与**在线统计**（是否在线、全网套数）独立，后者默认开启，见 [在线统计与社区主站](../community_stats.md)。

## 语料来源

| 来源 | 说明 | 默认 |
| --- | --- | --- |
| 本机 | 日常接话、学习、清理 | 开启 |
| 共享池 | 社区中心接话素材 | 关闭，需 WebUI 手动开 |
| 联邦库 | 多套牛牛共用独立库 | 进阶，多数部署未接 |

查找顺序默认**先本机再共享池**；远端失败自动退回本机。架构见 [控制面与语料联邦](../../architecture/control-plane-corpus-federation.md)。

## 配置

| 项 | 说明 |
| --- | --- |
| WebUI | **通用配置 → 语料联邦** |
| 落盘 | `data/pallas_config/webui.json` |
| 生效 | 保存后热重载，一般无需重启 |

在线统计与名册公开见 [在线统计与社区主站](../community_stats.md)（**通用配置 → 在线统计与社区主站**）。

### 分组说明

| 分组 | 做什么 |
| --- | --- |
| 接话时查哪些语料 | 查找顺序、重复句合并 |
| 社区共享语料 | 开关、登记、上传、地址与口令 |
| 接话性能 | 一般保持默认 |

### 常用键（`config/pallas.toml` `[corpus]`）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `community_enabled` | `false` | 使用共享语料 |
| `auto_enroll` | `false` | 自动向中心登记口令 |
| `community_contribute` | `auto` | 上传本机新回复 |
| `on_remote_failure` | `local_only` | 远端失败只用本机 |

关闭在线统计：`[community_stats] enabled = false`（见 [在线统计与社区主站](../community_stats.md)）。

### 联邦控制（多套牛牛共池）

**通用配置 → 联邦控制** 填入池密钥并开启去重，避免同一条群消息各回复一遍。密钥在 **统计与语料 → 社区联邦** 复制。

## 排障

| 现象 | 处理 |
| --- | --- |
| 共享池读不到 | 查开关、口令、网络；失败会退回本机 |
| 不想上传只读 | `community_contribute = false` |
| 跨机重复回复 | 确认联邦控制已入池且去重开启 |

## API 与运维

| 项 | 说明 |
| --- | --- |
| `GET /pallas/api/corpus-status` | 本部署状态 |
| `GET /pallas/api/local-corpus-hot` | 本机语料热词（`scope=global`） |
| `GET /pallas/api/community-corpus-hot` | 社区热词（`mode=pool\|recent\|fleet`） |
| `data/pallas_config/community_stats.json` | 部署编号、语料口令等 |

### 热词与同步

| 能力 | 说明 |
| --- | --- |
| 本机热词 | 控制台「本机语料热词」；累计本部署全部群学习语料 |
| 社区高频池 | `mode=pool`，不按时间截断 |
| 近期活跃 | `mode=recent` + 日/周/月 |
| backfill | WebUI **通用配置 → 语料联邦 → 历史语料同步**，或 `PALLAS_CORPUS_BACKFILL_ENABLED=true` |
| 机群快照 | 心跳可选附带本机 Top 词，中心 `mode=fleet` 叠加展示 |

上传仅含关键词与短句，不含群号与 QQ。

## 实现

[`src/features/corpus/`](../../../src/features/corpus/) · 中心服务 [Community-Stats](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats)
