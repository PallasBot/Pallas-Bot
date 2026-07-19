# 升级

升级须对齐本体、官方插件、WebUI / AI Runtime / 协议端各层；任一层滞后可能导致服务可启动但行为异常。

## 升级前确认

- [ ] 升级范围：仅主仓，或含官方插件与前端资源
- [ ] 部署形态：单进程 / 分片
- [ ] 外部依赖：协议端、AI Runtime 是否接入
- [ ] 备份：`config/pallas.toml`、`data/`；按需备份数据库与协议端实例数据

上列未勾选完成前，勿直接上线升级。

## 推荐顺序

### CLI 一条流（源码部署）

在 Pallas-Bot 仓库根：

```bash
uv run pallas maintenance run \
  --update-bot \
  --update-webui \
  --dev
```

| 附加项 | 操作 |
| --- | --- |
| AI Runtime | Pallas-Bot-AI 仓 `git pull` 后执行 `uv run pallas ai setup` |
| 官方插件 | 一般随已装 pip 保留，升 4.0 不必重装；对齐 PyPI 新版时在控制台 **插件商店** 点「更新」 |

分步等价：`pallas update bot` → `pallas update webui` → `pallas sync` → `pallas restart`。详见 [CLI 参考](/maintainer/reference/cli)。

### 分步清单

1. **备份运行数据** — `config/pallas.toml`、`data/`；按需数据库与协议端数据
2. **升级主仓** — 代码与 `uv sync`；补齐新配置项
3. **升级官方插件** — 控制台 **插件商店** 查看版本；无 UI 时用 `pallas ext install` 覆盖
4. **同步 WebUI** — 页面或 API 契约变更时须同步静态资源至 `data/pb_webui/public/`
5. **联调协议端与 AI** — 验证地址、回调、字段未因版本漂移

## 单进程 vs 分片

| 形态 | 额外验证 |
| --- | --- |
| 单进程 | 启动、WebUI、协议端、关键插件 |
| 分片 | hub/worker 版本一致；共用 `data/` 无旧状态；registry、端口映射、协议端连到正确 worker |

## 升级后验证

- [ ] Bot 正常启动
- [ ] WebUI 可打开且非旧静态资源
- [ ] `/pallas/api/health` 与基础状态接口正常
- [ ] 协议端在线，账号状态正确
- [ ] 官方插件列表、治理页、命令权限页正常
- [ ] AI Runtime（若接入）：最小任务走通
- [ ] 分片（若适用）：worker 聚合状态正常

## 常见故障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 页面样式或字段像旧版 | WebUI 静态资源未同步 | 执行 `pallas update webui` 或维护流中的 WebUI 同步步骤 |
| 插件行为与帮助不一致 | 主仓与扩展版本不对齐 | 插件商店更新；核对治理与元数据能力 |
| 分片状态异常、进程均在线 | registry / 共用 data / 聚合接口 / 协议端连错 worker | 查 `data/pallas_shard/` 日志与 `registry.json` |

## 升级策略

- 一次升级一类环境；升级后立即做最小回归
- 区分「主仓升级」与「整套运行环境升级」
- 协议端、AI Runtime、WebUI、主仓分步执行，保留回退路径

## 站点定制：更新时不丢本地改动

| 内容 | 位置 | 更新主仓时 |
| --- | --- | --- |
| 监听、数据库、超管 | `config/pallas.toml` | 保留 |
| 插件 / 通用配置 | `data/pallas_config/webui.json` | 保留 |
| 运行数据、协议实例 | `data/` | 保留 |
| 站点自有插件 | `local/plugins/` + `extra_plugin_dirs` | 保留 |

避免直接改已跟踪源码；否则「应用 Bot 更新」需 stash / 手工合并。

### 站点自有插件

1. 代码置于 `local/plugins/<插件名>/`（NoneBot 插件结构）
2. `config/pallas.toml`：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

3. 重启 Bot（分片须重启 hub 与对应 worker）
4. 与官方 / 内置插件同名时 **local 优先**

社区与官方插件商店：[社区插件商店](/guide/community-plugin-store) · [安装插件](/guide/install-plugins)

### 部署形态与更新方式

控制台「版本与更新 → Bot 本体」检测 `deployment_mode`：

| 模式 | 含义 | 推荐更新 |
| --- | --- | --- |
| `docker` | 非 git 工作副本 | `docker compose pull` + `up -d` |
| `release_tag` | HEAD 在 Release tag 且干净 | WebUI「应用 Bot 更新」或 `git checkout --detach vX.Y.Z` |
| `release_tag_dirty` | tag 上有本地改动 | 先迁定制到 `local/`；更新会 stash → checkout → stash pop |
| `dev_clone` | 非精确 tag（如 `main`） | `git pull --ff-only --autostash` |

Docker 可挂载 `./pallas-bot/local/plugins:/app/local/plugins`；镜像更新只替换代码，挂载的插件与 `data/`、`config/` 保留。

### Docker 外挂插件卷

[`docker-compose.yml`](https://github.com/PallasBot/Pallas-Bot/blob/main/docker-compose.yml) 可选挂载：

```yaml
- ./pallas-bot/local/plugins:/app/local/plugins
```

宿主机 `pallas-bot/config/pallas.toml` 中设置 `extra_plugin_dirs = ["local/plugins"]`。

### 生产门禁：重复命令 prefix

local 整包覆盖与官方插件并存时，可能重复注册同一口令。生产建议：

```toml
[env]
PALLAS_DUPLICATE_PREFIX_STRICT = "true"
```

检测到冲突时阻断启动。

## 相关文档

- [运维入口](/maintainer/quickstart)
- [配置参考](/maintainer/reference/config)
- [配置存储](/developer/architecture/config-storage)
- [WebUI](/maintainer/install/webui)
- [协议端](/maintainer/install/protocol)
- [LLM 与 AI 运维](/maintainer/operate/llm-and-ai)
- [3.0 迁移](/about/migration)
