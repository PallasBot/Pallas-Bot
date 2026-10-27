# 方舟查询与 HTTP MCP

Pallas 将干员、技能、敌人结构化查询与 PRTS 资料检索作为产品能力。Bot 的 LLM 工具和独立 MCP 服务共用查询逻辑，不通过聊天模型绕回自身。

## 分层与数据流

```text
Bot LLM tools ──────┐
                   ├─ arknights_kb.service ── domain/arknights 本地结构化表
HTTP MCP 只读工具 ──┘                      └─ PRTS 本地资料快照
```

- `pallas/core/domain/arknights/`：既有结构化数据与查询函数。
- `pallas/product/arknights_kb/`：输入校验、统一查询结果、来源状态与 PRTS 资料消费。
- `pallas/product/llm/tools/`：Bot 工具适配，继续遵守 Bot 的工具选择与上下文约束。
- `pallas/product/arknights_mcp/`：独立 HTTP 服务、查询身份与资源边界，不执行整个内部工具注册表。
- CLI：管理员在本机管理查询凭据与资料更新；这些管理动作不是 MCP 工具。

MCP 不要求开启 `LLM_TOOLS_ENABLED`，不依赖群聊、数据库中的私人记忆或运行中的 Bot；仍遵守 `ARKNIGHTS_KB_ENABLED` 及 PRTS 产品开关。

## 工具范围

| scope | 工具 |
| --- | --- |
| `arknights:read` | `arknights.operator.get`、`arknights.operator.search`、`arknights.skill.get`、`arknights.enemy.get`、`arknights.enemy.search` |
| `prts:read` | `prts.search`、`prts.read`、`prts.timeline` |

不开放群消息投递、管理接口、私人记忆、账号数据、下载任务或任意本地文件读取。`read_only` 注解是客户端提示，真正的限制由静态工具白名单、调用级 scope 与服务输入校验共同执行。

服务结果区分输入错误、源禁用、源不可用与正常未命中；缺数据不自动联网下载。结构化表可能只覆盖部分干员，不能把部分覆盖当作完整图鉴；来源标识不等同于精确游戏版本或实时性证明。

### 检索边界与缓存

`prts.search` 先按 metadata（game / resource_type / 名称类过滤）在加载索引与正文之前筛选，eligible 为空时直接返回正常 0 结果。候选按最终 title 值稳定排序后按 `(pack_id, shard_path)` 分组，每个分片只加载并校验一次；全局只保留旧排名（正文命中优先、同分按 title 稳定）的前 K 条，并仅在后续分片不可能超过第 K 名时安全提前停止。返回条数、单次累计解压与并发仍有上限，宽泛或罕见查询可能因解压预算失败（真实错误，不伪装成 0 结果）。

倒排索引的长期缓存只保留解压后的 raw bytes，且只为本次查询命中的 grams 构建 postings；其余条目仍完整校验格式（header / offset 表 / varint / UTF-8）但不保留列表，校验通过后才发布缓存，异常不留坏 raw。raw 缓存的字节预算是容器内存预算的一部分，不是 RSS 保证；计费、代际清理与错误语义不变。索引文件仍会被整体遍历，未匹配候选很多时仍可能触发解压预算，不宣称查询复杂度已完全解决。

## 资料与配置

PRTS 从 PRTS.chat release 指定的公开来源按需下载，保留 manifest 与来源定位；查询只读取已安装资料。资料不随 wheel、Docker 或 Bot release 打包。

| 配置 | 用途 |
| --- | --- |
| `ARKNIGHTS_KB_ENABLED` | 两类查询的总开关 |
| `ARKNIGHTS_KB_AUTO_SYNC` | 既有 Bot 结构化表缺失时的自动同步；不意味着 MCP 查询会联网 |
| `PRTS_CORPUS_ENABLED` | PRTS 查询开关 |
| `PRTS_CORPUS_PACKS` | 启用的 PRTS 分区 |
| `PRTS_CORPUS_INCLUDE_ENDFIELD` | 按需包含终末地资料 |
| `PRTS_CORPUS_SEARCH_LIMIT` | 单次资料检索条数上限 |
| `PRTS_CORPUS_READ_MAX_LINES` / `PRTS_CORPUS_READ_MAX_CHARS` | 原文读取预算 |
| `PRTS_CORPUS_DOWNLOAD_TIMEOUT_SEC` | 管理员更新时的下载超时 |
| `PRTS_CORPUS_CACHE_MAX_MB` / `PRTS_CORPUS_QUERY_MAX_MB` | 缓存与单次累计解压预算，各默认64 MiB，修改后重启服务生效；不是RSS保证 |

配置仍按 `pallas.toml → 遗留环境配置 → webui.json` 合并，见 [配置存储](config-storage.md)。本地资料目录沿用 `data/prts_corpus/`，MCP 凭据独立落在 `data/pallas_mcp/`。

PRTS 更新先校验完整新快照再发布指针，失败保留旧资料。运行中的请求只读取其选定的数据代，不混合更新前后内容。首版不在服务启动或查询时自动下载 PRTS。

## 身份、部署与兼容边界

MCP 使用独立 `pmcp_` 预配查询密钥，只存摘要；console 的 `pls_` 管理身份不能用于 MCP，MCP 身份不能登录控制台。密钥按调用方签发，撤销后拒绝后续请求，不取消已授权的在途请求。

首版适配支持自定义 `Authorization: Bearer …` 的 Streamable HTTP 客户端；不提供 OAuth 登录、动态注册或 OAuth 自动发现，不伪造授权服务器元数据。
托管修改版可用 `--source-url https://mcp.example.com/mcp-source.tar.gz` 提供对应运行源码；该地址会出现在客户端初始化说明中。应用默认关闭 access log，凭据不得放入 URL。

### 公共只读模式

`pallas mcp serve --public-readonly`（`create_app(public_readonly=True)`）是显式的 opt-in：此时无需 `Authorization`，也不读取本地密钥库，官方 legacy 与默认 modern 客户端可直接 initialize / list / call 固定 8 个只读工具。默认与现有自部署 compose 仍强制 Bearer，不会因该参数把其它部署变匿名。

公共请求使用一个固定全局只读身份（两只读 scope）接入既有 rate limiter，因此与私钥请求一样受应用全局请求上限与并发约束；这是公共共享预算，不是逐调用方配额。Authorization 头即使存在也不扩大能力，仍只能访问同一固定工具集；`X-Forwarded-For` 等用户可伪造的身份头不被信任。该固定身份不读取本地密钥库，因此不受 `pallas mcp revoke` 影响（撤销只作用于 private 模式的 `pmcp_` 密钥）。Host/Origin/请求体上限、源 URL 校验与 access log 关闭在两种模式下一致，不开放内部注册表、管理接口、文件写入或资料同步。

真实调用方 IP 的限流由部署侧反向代理承担：经隧道/代理后应用看不到原始 IP，也不应直接信任 `X-Forwarded-For`，需在代理对该 MCP vhost 按 IP 限流。应用不因此开启任意 Origin 或 CORS 反射。

在仓库根目录管理本机服务：

```bash
# 检查资料；需要 PRTS 检索时再显式下载（会访问上游并占用本地磁盘）
uv run pallas mcp corpus status
uv run pallas mcp corpus update

# 为一个调用方签发只读密钥；明文仅显示一次
uv run pallas mcp token --label external-agent --scope arknights:read --scope prts:read
uv run pallas mcp tokens

# 默认仅监听本机；不是启动整个 Bot
uv run pallas mcp serve

# 撤销一个调用方
uv run pallas mcp revoke <key-id>
```

结构化表沿用 Bot 的方舟知识库同步。新站若仅运行 MCP、尚未准备这些表，可由本机管理员显式调用既有同步入口；以下操作会访问游戏数据上游，查询请求本身不会触发它：

```bash
uv run python -c 'from pallas.core.domain.arknights.sync import kb_sync_plan, run_arknights_sync; print(run_arknights_sync(kb_sync_plan(avatars=False)))'
```

客户端地址为 `http://127.0.0.1:8765/mcp`，请求头为 `Authorization: Bearer <签发的密钥>`。如客户端在另一台机器上，应填写管理员实际配置的 HTTPS 地址，而非该回环地址。
若通过反向代理保留公网 Host，启动时用 `--allowed-host mcp.example.com` 明确允许；浏览器客户端携带 Origin 时另用 `--allowed-origin https://client.example.com` 精确放行。参数可重复，不支持通配符。
直接非回环监听需显式 `--allow-remote --host <监听地址> --allowed-host <实际Host>`；仅应在确认网络边界后使用。不要将示例视作 TLS、代理或公网访问已经配置完成。

服务默认仅监听回环地址。远程使用应显式配置允许的 Host/Origin，并在可信反向代理处启用 TLS；不因能启动服务就默认已适合公网开放。不得把凭据放入 URL、日志或提交到仓库。

请求体、参数、输出与实际查询并发均有上限；私有模式按已认证查询身份限流，公共只读模式则共用同一全局预算。首版是单进程内限流，不承诺多实例共享配额，也不把协程取消当作后台查询线程已停止。

## 旧插件迁移

内建 PRTS 取代历史 `local/plugins/prts_corpus` 的查询实现。加载器在旧插件导入前跳过它，避免重复工具与后台下载；不会删除插件文件或自动重写用户配置。
旧插件的群内更新命令不作为新接口承诺；改用本机 MCP CLI 管理资料。内建配置在「方舟知识库」通用段维护，旧插件的配置不自动等价迁移。

## 来源与使用条件

- 结构化数据来自 [ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData)。
- PRTS 资料来自 [PRTS.chat](https://prts.chat/) 及其 [明日方舟数据集](https://modelscope.cn/datasets/HTiantian/prts-agent-corpus-arknights)，相关项目为 [PRTS Terrarchive](https://github.com/HTian-qwq/prts-terrarchive)。

Pallas 的代码许可证不替代游戏原文、Wiki 或各 pack 的内容条款。管理员下载或对外提供片段前应核对对应来源的使用条件并保留出处；manifest 允许公开下载不自动证明任意商业再分发或公网服务均获授权。
本路线不包含本地 `docs/agent/` 研究快照，也不把角色试验材料当公开资料源。
