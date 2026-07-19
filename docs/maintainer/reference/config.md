# 配置参考

配置索引：来源、覆盖顺序、热生效与重启边界。

## 三类来源

| 来源 | 路径 | 内容 |
| --- | --- | --- |
| 主配置 | `config/pallas.toml` | 监听、端口、数据库、基础环境、角色与部署前提 |
| WebUI 落盘 | `data/pallas_config/webui.json` | 插件页、通用段、命令权限、策略与治理项 |
| 遗留 `.env` | 根目录 `.env` / `.env.{ENVIRONMENT}` | 仅兼容旧项或第三方插件；不再作为主入口 |

最终运行值以 WebUI 覆盖优先级最高。

## 主要配置入口

| 配置类型 | 位置 | 何时改 |
| --- | --- | --- |
| 主运行配置 | `config/pallas.toml` | 监听地址、端口、数据库、superusers、基础环境 |
| 运行中通用配置 | `data/pallas_config/webui.json` | WebUI 保存的插件与通用配置 |
| 遗留兼容环境变量 | `.env` | 仅兼容或第三方插件相关 |

## 覆盖顺序

低 → 高：

1. `pallas.toml`
2. `.env` / `.env.{ENVIRONMENT}`
3. `webui.json`

| 现象 | 原因 |
| --- | --- |
| `pallas.toml` 改对了但不生效 | 同名键已被 `webui.json` 覆盖 |
| WebUI 保存过同名项 | 最终值优先看 `webui.json` |

## 通常需重启

- 端口变更
- 数据库连接变更
- 启停角色或分片方式变更
- 主进程启动链相关环境变更
- 官方插件安装、卸载、升级

## 通常可直接生效

- 插件开关类配置
- 通用配置段
- 命令权限
- 冷却、阈值、策略型配置
- 已接入热重载的插件页配置

::: warning
能否立即生效还取决于：

- 插件是否接入 `install_hot_reload_config`
- 配置是否只影响运行态
- 分片下 worker 是否能读到共享落盘
:::

## 分片

- hub 与 worker 共用同一份 `data/pallas_config/webui.json`
- worker 能感知磁盘修订变化
- 「WebUI 显示保存成功，行为没变」：先查共享 `data/` 与落盘文件

## 排障顺序

1. 改的是 `pallas.toml`、WebUI，还是遗留 `.env`
2. 该键是否被 `webui.json` 覆盖
3. 启动配置还是运行态配置
4. 应热生效还是需重启
5. 分片下 worker 是否读到新值

## 常见误判

### 改了 `pallas.toml`，行为没变

- 同名键已被 WebUI 覆盖
- 启动层配置未重启进程

### WebUI 保存成功，行为没变

- 插件未接热重载
- 该配置本来需重启
- 分片 worker 未看到共享落盘更新

### `.env` 改了与预期不符

- 该键不应再以 `.env` 为主入口
- 或已被更高优先级的 WebUI 落盘覆盖

## Docker 挂载与迁移

| 宿主机 | 容器内 |
| --- | --- |
| `pallas-bot/config/pallas.toml` | `/app/config/pallas.toml` |
| `pallas-bot/data/` | `/app/data/` |

从旧 `.env` 一次性迁移：

```bash
uv run python tools/migrate_env_to_pallas.py
```

## 相关阅读

| 目标 | 文档 |
| --- | --- |
| 合并顺序与读取 API | [配置存储](/developer/architecture/config-storage) |
| 本机跑通 | [五分钟跑起来](../../guide/quickstart.md) |
| 部署形态 | [运维入口](/maintainer/quickstart) |
| 运行中配置 | [WebUI 运维](/maintainer/operate/webui) |
| 保存后不生效 | [排障](/maintainer/operate/troubleshooting) |
| 站点定制与更新 | [升级](/maintainer/deploy/upgrade) |
