# 语料联邦

管理牛牛**接话时从哪里找回复素材**：默认只用**本机数据库**；可选接入**社区共享池**，读取或上传大家贡献的短句接话。

> **在线统计**（是否在线、全网有多少套牛牛）是另一套能力，默认开启，见 [社区在线统计](../community_stats.md)。

## 三个语料来源

| 来源 | 存在哪 | 典型用途 | 当前状态 |
| --- | --- | --- | --- |
| **本机** | 本部署业务库 | 日常接话、学习、清理 | ✅ 默认启用 |
| **共享池** | 社区中心 | 读取/上传社区接话素材 | ✅ 需在 WebUI 手动开启 |
| **联邦库** | 独立数据库 | 多套牛牛共用同一语料库 | ⏳ 进阶能力，多数部署尚未接入 |

默认查找顺序：**先本机，再共享池**（未开共享池时只查本机）。访问共享池失败时自动退回本机，不阻塞启动。

架构细节见 [控制面与语料联邦](../../architecture/control-plane-corpus-federation.md)（维护者向）。中心服务见 [Pallas-Bot-Community-Stats](https://github.com/TogetsuDo/Pallas-Bot-Community-Stats)。

## 默认行为（升级后）

| 项目 | 默认 | 说明 |
| --- | --- | --- |
| 本机语料 | 开启 | 接话与学习始终写本机 |
| 共享语料 | **关闭** | 需在 WebUI 打开「使用共享语料」 |
| 在线统计 | 开启 | 与语料独立，见 [社区在线统计](../community_stats.md) |
| 上传新回复 | 自动 | 接入共享池后，默认允许把本机新学到的回复同步上去 |
| 自动登记 | 关闭 | 开启共享语料后，程序会向中心登记访问口令并保存在本机 |

主站不可用时，程序会自动尝试备站访问共享池（与在线统计相同策略）。

## 怎么配置

### 控制台（推荐）

1. 打开 **通用配置 → 语料联邦**（侧栏也可进 **统计与语料 → 语料设置**）。
2. 按需修改各分组项，点 **保存配置**；写入 `webui.json` 并热重载，一般无需重启。

分组说明：

| 分组 | 做什么 |
| --- | --- |
| 接话时查哪些语料 | 查找顺序、重复句合并方式 |
| 社区共享语料 | 开关、登记、上传、共享池地址与口令 |
| 在线统计与社区主站 | 是否上报在线数据、是否公开牛牛名册 |
| 接话性能 | 一般保持默认即可 |

**统计与语料** 页只看状态，不改配置。

### 配置文件（可选）

`config/pallas.toml` 示例：

```toml
[corpus]
community_enabled = false       # 共享语料：默认关
auto_enroll = "false"
community_contribute = "auto"   # 接入后默认允许上传；要关上传：false
on_remote_failure = "local_only"

# 手动填写口令（跳过自动登记）：
# [corpus.community]
# api_base = "https://stats.pallasbot.top/v1/corpus"
# token = "pc_..."
```

等价环境变量：`PALLAS_CORPUS_*`（见 `src/features/corpus/config.py`）。

### 常见操作

**开启共享语料**

- WebUI：语料联邦 → 社区共享语料 → 打开「使用共享语料」
- 或配置：`community_enabled = true`

**关闭共享语料**

```toml
[corpus]
community_enabled = false
```

**只关上传、继续读取**

```toml
[corpus]
community_contribute = false
```

**关闭在线统计**（同时不再有自动登记）

```toml
[community_stats]
enabled = false
```

## 联邦控制（多套牛牛共池）

若多套牛牛加入同一**社区联邦池**，需要在 **通用配置 → 联邦控制** 填写入池密钥，并开启消息去重，避免对同一条群消息各回复一遍。

入池密钥在 **统计与语料 → 社区联邦** 面板复制。与共享语料口令、在线统计无关。

## 运维接口

| 项 | 说明 |
| --- | --- |
| 本部署状态 | `GET /pallas/api/corpus-status` |
| 社区聚合 | `GET /pallas/api/community-stats` |
| 本地落盘 | `data/pallas_config/community_stats.json`（部署编号 + 语料口令等） |
| 预灌样本 | `uv run python tools/seed_community_corpus.py`（运维向中心贡献测试语料） |

## 隐私说明

- 上传到共享池的只有**关键词与短句回复**，匿名处理，不含群号与 QQ。
- 社区中心不可达时，接话与学习仍走本机；上传失败不会造成反复重试风暴。

## 相关文档

- [社区在线统计](../community_stats.md)
- [配置存储](../../architecture/settings-storage.md)
