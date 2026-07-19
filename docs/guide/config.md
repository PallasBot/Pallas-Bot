# 配置从哪改

Pallas-Bot 没有单一「大配置文件」。三处怎么分工见下表。

::: tip 💡 推荐
**日常改配置优先用网页控制台**（插件开关、通用项、命令权限、AI / 语料等）；保存后写入 `data/pallas_config/webui.json`，多数可立刻生效。怎么打开、侧栏去哪 → [网页控制台](web-console.md)。
:::

::: tip
第一次部署：先改 `config/pallas.toml` 里的超管与数据库，启动后再用控制台改其余项。端口、数据库等进程级项仍改 `pallas.toml`。
:::

## 三处分别管什么

| 改哪里 | 路径 | 典型内容 |
| --- | --- | --- |
| **主配置** | `config/pallas.toml` | 监听地址 / 端口、超管 `superusers`、数据库 |
| **网页控制台** | 保存后落盘 `data/pallas_config/webui.json` | 插件开关、通用配置、命令权限、AI / 语料等 |
| **遗留 `.env`** | 根目录（可选） | 仅兼容旧项或第三方 nb 插件；**不要**再往里加主能力键 |

覆盖顺序（后者优先）：

```text
pallas.toml  →  .env  →  webui.json
```

所以：控制台保存过的同名项，会盖住 `pallas.toml` 里的值。排障时别只看刚改的那一处。

## 常见项去哪改

| 想改什么 | 去哪 |
| --- | --- |
| 超管 QQ | `pallas.toml` → `[bootstrap] superusers` |
| 号主 | 控制台 **实例与连接**；见 [号主](bot-owner.md) |
| 端口 / 数据库 | `pallas.toml` → `[bootstrap]` |
| 装 / 卸官方插件 | 控制台 **插件商店** |
| 插件开关、冷却、命令权限 | 控制台对应页 / **命令权限** |
| AI、语料、外部服务地址 | 控制台 **通用配置** |
| 控制台登录口令 | 启动日志初始口令；遗忘见 [FAQ](/deploy/faq) |

示例主配置（最少能跑）：

```toml
[bootstrap]
host = "0.0.0.0"
port = 8088
superusers = ["你的QQ号"]
db_backend = "postgresql"

[bootstrap.postgres]
host = "127.0.0.1"
port = 5432
user = "pallas"
password = "pallas"
db = "PallasBot"
```

从 `config/pallas.example.toml` 复制为 `config/pallas.toml` 再改。

## 保存后要不要重启

| 通常要重启 | 通常可立刻生效 |
| --- | --- |
| 端口、数据库连接 | 多数插件页配置（已接热重载） |
| 分片 / 进程角色 | 通用配置段、命令权限 |
| 官方插件装 / 卸 / 升级 | 冷却、策略类开关 |

不确定时：控制台提示「需重启」就重启；仍不对再查是否被 `webui.json` 覆盖。

## 相关阅读

| 文档 | 何时看 |
| --- | --- |
| [网页控制台](web-console.md) | 怎么打开、登录、常用面板 |
| [号主](bot-owner.md) | 配 `admins` |
| [配置要点（生产）](/deploy/config) | 部署检查清单与 `[bootstrap]` 细节 |
| [配置参考](/maintainer/reference/config) | 热生效边界与排障顺序 |
| [配置存储](/developer/architecture/config-storage) | 开发向合并与读取合同 |
