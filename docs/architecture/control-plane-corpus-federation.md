# 控制面、联邦语料与外接语料

**维护者向**：Bot 侧 Composite 语料、Bootstrap、联邦 ingress 与中心 OpenAPI 设计说明。

> 部署者与群管请读 [语料联邦](../common/corpus/README.md) 与 [在线统计](../common/community_stats.md)。

> **Phase 1**：`local` + **community** 多读源、auto enroll、contribute 默认开、主/备语料读 failover、WebUI 语料联邦配置与 `/corpus-status`。  
> **Phase 2**：**ingress 去重**（`src/platform/federate/` + `ingress_gate`）已接入；**fed** 第二 PG、`bootstrap`、fleet 快照仍待交付。

## 域名与部署

| 阶段 | 示例子域 | 用途 |
|------|----------|------|
| **现已上线** | `stats.pallasbot.top` | 心跳、`/v1/stats`、**`/v1/corpus/*`** |
| 备案过渡期 | `pallas.togetsudo.com` | Bot 自动回退 |
| 后续扩展 | 如 `control.pallasbot.top` | Bootstrap、Tenant、联邦 |

Bot **auto enroll** 从 `[community_stats]` 心跳地址推导语料 URL。auto 模式下 enroll 落盘**实际连上的** `api_base`；读路径按心跳主/备顺序 **failover**。

## 目标与档位

| 档位 | 业务库 | 联邦语料 `corpus_fed` | 社区语料 `corpus_community` | 协调 Redis |
|------|--------|----------------------|----------------------------|------------|
| 自托管（现状） | 本地 `PG_*` | — | 可选 enroll | 可选 join 联邦 |
| 自托管 + 外接 | 本地 | — | ✅ API | 可选 |
| 全量托管 | 中心下发 `pbiz_*` | ✅ `pcorpus_{fed}` | 可选 | ✅ |
| 全量 + 社区 | 中心下发 | ✅ | ✅ 三路 merge | ✅ |

逻辑身份：

- `deployment_id`：沿用 `community_stats` 本地 UUID（`load_or_create_deployment_id()`）
- `tenant_id`：全量档位；控制面签发
- `federate_id`：联邦池；共享 `pcorpus_*` 与 Redis prefix
- 用户**不配置**业务库名；自托管继续使用默认 `PallasBot` 即可

## Bot 语料源与 merge

接话（`responder._context_find_with_pool`）读取语料；学习（`learner`）写入语料。

```text
merge_order 默认: ["local", "fed", "community"]

find_by_keywords(keywords):
  candidates = {}
  for source in merge_order:
      ctx = await source.find_by_keywords(keywords)
      merge_answers(candidates, ctx, weight=source.weight)

learn / upsert_answer / insert:
  始终写 local
  若 fed_contribute   → 异步写 corpus_fed
  若 community_contribute → 异步 POST /v1/corpus/contribute
  ban / replace_answers / delete_expired → 仅 local（fed 清理仅全量运维）
```

`merge_strategy`：

- `local_first`：local 有满足阈值的候选则不再采纳远端 answer（仍可用远端补 pool）
- `merge_counts`：同 `(group_id, answer_keywords)` 的 `count` 相加后参与阈值判断

远端失败：`on_remote_failure = local_only`，不阻塞启动（与 `community_stats` 一致）。

---

## CompositeContextRepository

实现 `ContextRepository` Protocol（`src/foundation/db/repository.py`），对 repeater 透明替换 `make_context_repository()` 的默认返回值。

### 模块布局（建议）

```text
src/features/corpus/
  __init__.py
  config.py              # [corpus] / bootstrap 合并配置
  merge.py               # Context / Answer 合并
  composite_repo.py      # CompositeContextRepository
  local_source.py        # 包装现有 Pg/Mongo ContextRepository
  fed_source.py          # 第二 PG 连接（PG_CORPUS_FED_*）或 bootstrap db.corpus_fed
  community_source.py    # HTTP RemoteCorpusRepository
  bootstrap_client.py    # GET /v1/bootstrap
  enroll_client.py       # POST /v1/corpus/enroll
  write_fanout.py        # learn 异步 mirror 到 fed/community
```

### 类 sketch

```python
@dataclass(frozen=True)
class CorpusSourceSpec:
    id: str  # "local" | "fed" | "community"
    readable: bool
    writable: bool
    weight: float = 1.0


class CompositeContextRepository:
    """多读源 merge；写路由 local + 可选异步 mirror。"""

    def __init__(
        self,
        local: ContextRepository,
        *,
        fed: ContextRepository | None = None,
        community: ContextRepository | None = None,
        merge_order: list[str] | None = None,
        merge_strategy: str = "local_first",
    ): ...

    async def find_by_keywords(self, keywords: str) -> Context | None:
        merged = None
        for spec_id in self._merge_order:
            repo = self._repo_for(spec_id)
            if repo is None:
                continue
            ctx = await repo.find_by_keywords(keywords)
            merged = merge_contexts(merged, ctx, strategy=self._merge_strategy)
        return merged

    async def context_exists_by_keywords(self, keywords: str) -> bool:
        if await self._local.context_exists_by_keywords(keywords):
            return True
        for repo in (self._fed, self._community):
            if repo and await repo.context_exists_by_keywords(keywords):
                return True
        return False

    async def upsert_answer(self, ...) -> None:
        await self._local.upsert_answer(...)
        await schedule_corpus_mirror("upsert_answer", ...)

    async def insert(self, context: Context) -> None:
        await self._local.insert(context)
        await schedule_corpus_mirror("insert", context=context)

    async def save(self, context: Context) -> None:
        await self._local.save(context)

    async def append_ban(self, keywords: str, ban: Ban) -> None:
        await self._local.append_ban(keywords, ban)

    async def replace_answers(self, keywords: str, answers: list[Answer], clear_time: int) -> None:
        await self._local.replace_answers(keywords, answers, clear_time)

    async def delete_expired(self, expiration: int, threshold: int) -> None:
        await self._local.delete_expired(expiration, threshold)

    async def find_for_cleanup(self, trigger_threshold: int, expiration: int) -> list[Context]:
        return await self._local.find_for_cleanup(trigger_threshold, expiration)
```

### RemoteCorpusRepository（HTTP）

仅实现 repeater **读路径** + **contribute 写路径**；清理/ ban 走 no-op 或 501。

| Protocol 方法 | HTTP |
|---------------|------|
| `find_by_keywords` | `GET /v1/corpus/context?keywords=` |
| `context_exists_by_keywords` | `HEAD /v1/corpus/context?keywords=` 或 GET 404 |
| `upsert_answer` | `POST /v1/corpus/contribute` body 见 OpenAPI |
| `insert` | `POST /v1/corpus/contribute`（type=new_context） |

### make_context_repository 改造

```python
def make_context_repository() -> ContextRepository:
    local = _make_local_context_repository()  # 现有 PG/Mongo 工厂
    cfg = get_corpus_config()
    if not cfg.any_remote_enabled():
        return local
    return CompositeContextRepository(
        local,
        fed=_make_fed_repository(cfg) if cfg.fed_enabled else None,
        community=_make_community_repository(cfg) if cfg.community_enabled else None,
        merge_order=cfg.merge_order,
        merge_strategy=cfg.merge_strategy,
    )
```

### init_db 扩展

- `local`：现有 `init_postgresql_db()` / `init_mongodb_db()`
- `fed`：可选 `init_corpus_fed_pg()`（独立 engine，`PG_CORPUS_FED_*` 或 bootstrap 注入）
- `community`：无 DB init；启动时 `corpus/enroll` 或 bootstrap 刷新 token

---

## 配置（pallas.toml 草案）

```toml
[control_plane]
enabled = false
bootstrap_url = "https://stats.pallasbot.top/v1/bootstrap"
# PALLAS_INSTANCE_SECRET 环境变量或 data 落盘，勿提交 git

[corpus]
local_enabled = true
fed_enabled = "auto"       # auto | true | false
community_enabled = "auto"
merge_order = ["local", "fed", "community"]
merge_strategy = "local_first"   # local_first | merge_counts
fed_contribute = true
community_contribute = false
on_remote_failure = "local_only"

# 外接社区（无 bootstrap 时）
# [corpus.community]
# api_base = "https://stats.pallasbot.top/v1/corpus"
# PALLAS_CORPUS_TOKEN=...

# 联邦第二 PG（bootstrap 可覆盖）
# [corpus.fed] → PG_CORPUS_FED_HOST / DATABASE / USER / PASSWORD
```

Bootstrap 响应字段见下文 OpenAPI `BootstrapResponse`。

---

## 控制面 OpenAPI 3.0（摘要）

Base URL（示例，可换其它 `*.pallasbot.top` 子域）：`https://stats.pallasbot.top`

### POST /v1/corpus/enroll

外接社区语料（无需 tenant）。

**Request**

```json
{
  "deployment_id": "uuid",
  "display_name": "optional",
  "invite_code": "optional"
}
```

**Response 200**

```json
{
  "corpus_token": "pc_xxxx",
  "api_base": "https://stats.pallasbot.top/v1/corpus",
  "policy": {
    "read": true,
    "contribute": false,
    "merge_strategy": "local_first",
    "read_rpm": 120,
    "contribute_per_day": 0
  },
  "expires_at": 1735689600
}
```

### GET /v1/corpus/context

**Headers:** `Authorization: Bearer pc_xxxx`

**Query:** `keywords` (required, string)

**Response 200** — 与 Bot `Context` JSON 同构（无 Mongo `_id` 亦可）

```json
{
  "keywords": "你好 早上",
  "time": 1716643200,
  "trigger_count": 12,
  "clear_time": 0,
  "answers": [
    {
      "keywords": "早啊",
      "group_id": 0,
      "count": 5,
      "time": 1716640000,
      "messages": ["早啊"]
    }
  ],
  "ban": []
}
```

`group_id: 0` 表示社区全局 anonymized 语料（Bot merge 时按 `cross_group_threshold` 处理）。

**Response 404** — 无记录

### POST /v1/corpus/contribute

**Headers:** `Authorization: Bearer pc_xxxx`（须 `policy.contribute=true`）

```json
{
  "op": "upsert_answer",
  "keywords": "你好 早上",
  "group_id": 0,
  "answer_keywords": "早啊",
  "answer_time": 1716643200,
  "message": "早啊",
  "append_on_existing": true,
  "deployment_id": "uuid"
}
```

或 `"op": "insert"` + 完整 `context` 对象。

**Response 202** — 已入队（可审核）  
**Response 200** — 已写入

### GET /v1/bootstrap

**Headers:**

- `Authorization: Bearer {instance_secret}`
- `X-Deployment-Id: {deployment_id}`

**Response 200** — 见 `BootstrapResponse`：

```yaml
BootstrapResponse:
  type: object
  required: [schema_version, deployment_id]
  properties:
    schema_version: { type: integer }
    tenant_id: { type: string, nullable: true }
    federate_id: { type: string, nullable: true }
    db:
      type: object
      properties:
        backend: { enum: [postgresql, mongodb] }
        business: { $ref: '#/components/schemas/DbConn' }
        corpus_fed: { $ref: '#/components/schemas/DbConn' }
    corpus_community:
      type: object
      properties:
        enabled: { type: boolean }
        api_base: { type: string }
        token: { type: string }
        read: { type: boolean }
        contribute: { type: boolean }
        merge_strategy: { type: string }
    coord:
      type: object
      properties:
        redis_url: { type: string }
        redis_prefix: { type: string }
        claim_ttl_sec: { type: integer }
    fleet:
      type: object
      properties:
        sync_url: { type: string }
        sync_interval_sec: { type: integer }
    expires_at: { type: integer }

DbConn:
  type: object
  properties:
    host: { type: string }
    port: { type: integer }
    database: { type: string }
    user: { type: string }
    password: { type: string }
    pool_size: { type: integer }
    max_overflow: { type: integer }
```

### POST /v1/heartbeat（扩展，向后兼容）

在现有 `community_stats` payload 上增加可选字段：

```json
{
  "deployment_id": "...",
  "tenant_id": "...",
  "federate_id": "...",
  "corpus": {
    "community_ok": true,
    "fed_ok": true
  }
}
```

**Response actions：**

```json
{
  "ok": true,
  "actions": [
    { "type": "refresh_bootstrap" },
    { "type": "corpus_reenroll" }
  ]
}
```

---

## Pallas-Bot 改动清单

### Phase 1（已交付）

| 路径 | 说明 |
|------|------|
| `src/features/corpus/` | config、merge、composite、community HTTP、enroll、status |
| `src/console/webui/corpus_federation_section.py` | WebUI「语料联邦」配置段 |
| `src/plugins/pallas_webui/extended_api.py` | `GET /corpus-status`、`/community-stats` 代理 |
| `tests/common/corpus/` | merge、composite、enroll、failover 等单测 |
| `tools/seed_community_corpus.py` | 向中心预灌语料（运维） |
| `docs/common/corpus/README.md` | 用户向说明 |

### Phase 1 已修改（节选）

| 路径 | 说明 |
|------|------|
| `src/foundation/db/__init__.py` | `make_context_repository()` 委托 composite |
| `src/foundation/config/repo_settings.py` | flatten `[corpus]`、`[community_stats]` |
| `config/pallas.example.toml` | `[corpus]` 示例注释 |

### Phase 2（ingress 已交付 / 其余待做）

| 路径 | 说明 |
|------|------|
| `src/platform/federate/` | ✅ `try_claim_cross_federate_message`、Redis 前缀 claim；⏳ fleet snapshot 客户端 |
| `src/platform/multi_bot/fleet.py` | ⏳ 合并远程 fleet QQ |
| `src/plugins/ingress_gate/__init__.py` | ✅ 联邦 ingress 抢占（fanout 前） |
| `src/plugins/repeater/__init__.py` | ✅ 复读路径二次校验 |

### 不宜改动

- `ban` / `blacklist` 仍只读本地库
- `MessageRepository` 首版不双轨（learn 上下文链仍 local；不足时再考虑）

---

## 实施顺序

1. ~~`corpus/merge.py` + `CompositeContextRepository` + 单测~~ ✅  
2. ~~`RemoteCorpusRepository` + enroll + HTTP 测试~~ ✅  
3. ~~控制面 `POST /v1/corpus/enroll`（Community-Stats）~~ ✅  
4. ~~WebUI / env：`[corpus]`、`/corpus-config`、首页状态~~ ✅  
5. ~~`bootstrap_client` + `[control_plane]` 协调 Redis 下发~~ ✅（`GET /v1/bootstrap` + Bot 落盘）；`corpus_fed` 第二 PG ⏳  
6. heartbeat `actions` + 增强 write_fanout ⏳  
7. ~~联邦 Redis + **ingress 去重**（Phase 2，非语料 block）~~ ✅（须 `PALLAS_FEDERATE_ID` + 共享 `REDIS_URL`）  

---

## 相关文档

- [语料联邦](../common/corpus/README.md)
- [社区统计](../common/community_stats.md)
- [多进程分片](bot_process_sharding.md)
- [配置存储](settings-storage.md)
