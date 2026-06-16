# 插件开发 Cookbook：牛牛赞我

> 从零跟做一只 **「牛牛赞我」** 插件：群内点赞计数、赞榜、控制台可改文案与冷却。  
> 适合第一次写 Pallas 插件；读完应能独立做「口令 + 配置 + 落盘 + 测试 + 文档」的完整闭环。

**预计阅读**：约 20 分钟（边读边敲约 1 小时）。

## 0、开始前

### 你需要已经

- 按 [本地开发环境](../environment.md) 跑通 Bot（`uv run nb run` 能登录 `/pallas/`）
- 协议端已连 QQ，群里能触发 **牛牛帮助**
- 编辑器推荐 VS Code；终端会在仓库根目录执行命令

### 本教程放哪

为不污染主仓 diff，插件放在 **`local/plugins/praise_me/`**（站点自有插件）。  
若要贡献上游，完成后整体挪到 `src/plugins/praise_me/` 并补 `tests/plugins/praise_me/`。

在 `config/pallas.toml` 增加：

```toml
[bootstrap]
extra_plugin_dirs = ["local/plugins"]
```

改完后 **重启 Bot**。

### 我们要做什么

| 口令 | 作用 |
| --- | --- |
| **牛牛赞我** | 给当前牛牛 +1 赞（每人有冷却） |
| **牛牛赞榜** | 本群点赞 Top 5，并显示你有多少赞 |

控制台可改：是否启用、点赞冷却秒数、点赞成功回复文案。

---

## 1、规划目录

养成先画结构的习惯。本插件很轻，但把「入口 / 配置 / 存储 / 业务」分开，后面好维护。

```text
local/plugins/praise_me/
├── __init__.py      # PluginMetadata + 注册 Matcher（保持短）
├── config.py        # Pydantic + WebUI 热重载
├── store.py         # 群级点赞计数（GroupPluginStorage + 纯函数，便于测）
└── handlers.py      # 命令处理逻辑
```

在仓库根执行：

```bash
mkdir -p local/plugins/praise_me
```

> **命名**：包名 `praise_me`（小写+下划线）；命令 ID 用 `praise_me.动作`。

---

## 2、配置与 WebUI 热重载

先写 `config.py`。控制台保存后应 **立即生效**，不要重启。

```python
# local/plugins/praise_me/config.py
from pydantic import BaseModel, Field

from src.console.webui import install_hot_reload_config


class Config(BaseModel, extra="ignore"):
    enable: bool = Field(default=True, description="是否启用点赞功能。")
    praise_cd_sec: int = Field(default=60, ge=0, description="同一用户两次「牛牛赞我」的最小间隔（秒）。")
    praise_reply: str = Field(
        default="谢谢夸奖！本群已收到你的 {total} 个赞～",
        description="点赞成功后的回复；可用 {total} 表示该用户在本群累计赞数。",
    )


plugin_webui = install_hot_reload_config(Config, config_module=__name__)
get_config = plugin_webui.get
```

要点：

- `Field(description=...)` 会出现在 WebUI 表单里，写给部署者看的话要清楚。
- 业务代码里 **始终** `get_config()`，不要在模块顶层 `cfg = get_config()` 后一直用旧对象。

保存后可在控制台 **插件** 页找到本插件项；改 `praise_reply` 再发「牛牛赞我」应立刻看到新文案。详见 [WebUI 插件配置](../../common/webui/README.md)。

---

## 3、数据落盘（按群计数）

群级结构化状态优先走 **声明式 `plugin_storage` + `GroupPluginStorage`**（写入 `GroupConfig` 文档的 `plugin_storage` 字段，与 help / duel 等同源）。  
**不要**再为这种小 JSON 手写 `data/<plugin>/groups/*.json`；`plugin_data_dir` 留给图片、导出、缓存等大文件（见 [插件结构 · 路径与持久化](structure.md)）。

在 `store.py` 封装读写；纯函数 `add_praise` / `top_praisers` 便于单测：

```python
# local/plugins/praise_me/store.py
from __future__ import annotations

from src.features.plugin_storage import GroupPluginStorage

PLUGIN_NAME = "praise_me"
COUNTS_KEY = "praise_counts"


async def load_counts(group_id: int) -> dict[str, int]:
    store = GroupPluginStorage(PLUGIN_NAME, group_id)
    raw = await store.get(COUNTS_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(k): int(v) for k, v in raw.items()}


async def save_counts(group_id: int, counts: dict[str, int]) -> None:
    store = GroupPluginStorage(PLUGIN_NAME, group_id)
    await store.set(COUNTS_KEY, counts)


def add_praise(counts: dict[str, int], user_id: str) -> int:
    counts[user_id] = counts.get(user_id, 0) + 1
    return counts[user_id]


def top_praisers(counts: dict[str, int], limit: int = 5) -> list[tuple[str, int]]:
    pairs = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return pairs[:limit]
```

要点：

- 存储键名 **`praise_counts`** 须在 `__init__.py` 的 `extra["plugin_storage"]` 声明（下一节一并写入）；未声明键在运行时会报 `PluginStorageKeyError`。
- 备份/迁移时随群配置走库；WebUI **插件能力** API 可看到已声明的 storage keys。

---

## 4、元数据、权限与帮助图

在 `__init__.py` 声明 `PluginMetadata`。帮助图文案格式见 [cmd_perm](../../common/cmd_perm/README.md)。

**推荐**用 [plugin_sdk](../../architecture/core-devx-roadmap.md#p1--plugin_sdk) 注册口令（权限 + 可选 CD 一次封装）：

```python
# local/plugins/praise_me/__init__.py
from nonebot.plugin import PluginMetadata

from src.features.cmd_perm.metadata_defaults import (
    PLUGIN_EXTRA_VERSION,
    PLUGIN_HOMEPAGE,
    PLUGIN_MENU_TEMPLATE,
)
from src.features.cmd_perm.metadata_text import SCENE_GROUP, join_usage, usage_line
from src.features.plugin_sdk import (
    bind_alias_handlers,
    command_limit_list,
    command_limit_row,
    command_perm_list,
    command_perm_row,
    group_command,
)
from src.features.plugin_storage import plugin_storage_list, plugin_storage_row

from .handlers import handle_praise, handle_rank

__plugin_meta__ = PluginMetadata(
    name="牛牛赞我",
    description="群内给牛牛点赞并查看赞榜。",
    usage=join_usage(
        usage_line("牛牛赞我", "给当前牛牛点赞"),
        usage_line("牛牛赞榜", "查看本群点赞排行"),
    ),
    type="application",
    homepage=PLUGIN_HOMEPAGE,
    supported_adapters={"~onebot.v11"},
    extra={
        "version": PLUGIN_EXTRA_VERSION,
        "menu_template": PLUGIN_MENU_TEMPLATE,
        "command_permissions": command_perm_list(
            command_perm_row("praise_me.praise", "牛牛赞我", "everyone"),
            command_perm_row("praise_me.rank", "牛牛赞榜", "everyone"),
        ),
        "command_limits": command_limit_list(
            command_limit_row("praise_me.praise", 0),
        ),
        "plugin_storage": plugin_storage_list(
            plugin_storage_row("praise_counts", scope="group", label="群内点赞计数"),
        ),
        "menu_data": [
            {
                "func": "牛牛赞我",
                "trigger_method": "on_command",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛赞我",
                "command_permission": "praise_me.praise",
                "brief_des": "给牛牛点赞",
                "detail_des": "为本群牛牛累计点赞；同一用户有冷却间隔，可在插件配置中修改。",
            },
            {
                "func": "牛牛赞榜",
                "trigger_method": "on_command",
                "trigger_scene": SCENE_GROUP,
                "trigger_condition": "牛牛赞榜",
                "command_permission": "praise_me.rank",
                "brief_des": "查看赞榜",
                "detail_des": "展示本群点赞 Top 5，并附带你本人的赞数。",
            },
        ],
    },
)

praise_cmd = group_command("praise_me.praise", "牛牛赞我", cd_sec=0)
rank_cmd = group_command("praise_me.rank", "牛牛赞榜", cd_sec=0)

bind_alias_handlers(praise_cmd, handle_praise)
bind_alias_handlers(rank_cmd, handle_rank)
```

仍可直接 `on_command` + `group_message_permission_for_command`（见 [getting-started](getting-started.md)）；新插件优先 SDK。

注意：

- 命令 ID `praise_me.praise` 在 metadata、matcher、`command_limits` 里 **必须一致**。
- `usage` / `trigger_condition` **不要**写「群管可用」——权限由 WebUI / cmd_perm 自动展示。
- `command_limits` 里 `praise` 填 `0`：默认 CD 由配置 `praise_cd_sec` 驱动，在 handler 里显式检查（下一节）。

---

## 5、命令处理与冷却

`handlers.py` 里接配置、CD、落盘。

```python
# local/plugins/praise_me/handlers.py
from src.features.command_limits import is_command_cooldown_ready, refresh_command_cooldown
from src.features.plugin_sdk import PluginHandlerContext

from .config import get_config
from .store import add_praise, load_counts, save_counts, top_praisers


async def handle_praise(ctx: PluginHandlerContext) -> None:
    cfg = get_config()
    if not cfg.enable:
        await ctx.finish("点赞功能已关闭。")

    cd = cfg.praise_cd_sec
    if cd > 0 and not await is_command_cooldown_ready(ctx.event, "praise_me.praise", cd):
        await ctx.finish(f"点太快啦，{cd} 秒后再赞吧。")
    if cd > 0:
        await refresh_command_cooldown(ctx.event, "praise_me.praise", cd)

    gid = ctx.group_id
    if gid is None:
        return
    uid = ctx.user_id
    counts = await load_counts(gid)
    total = add_praise(counts, uid)
    await save_counts(gid, counts)

    await ctx.finish(cfg.praise_reply.format(total=total))


async def handle_rank(ctx: PluginHandlerContext) -> None:
    cfg = get_config()
    if not cfg.enable:
        await ctx.finish("点赞功能已关闭。")

    gid = ctx.group_id
    if gid is None:
        return
    uid = ctx.user_id
    counts = await load_counts(gid)
    mine = counts.get(uid, 0)
    top = top_praisers(counts, limit=5)

    if not top:
        await ctx.finish("还没有人赞过牛牛，发送「牛牛赞我」抢第一个吧。")

    lines = [f"{i}. QQ {qq} — {n} 赞" for i, (qq, n) in enumerate(top, start=1)]
    body = "\n".join(lines)
    await ctx.finish(f"本群赞榜 Top {len(top)}：\n{body}\n\n你的赞数：{mine}")
```

说明：

- **存储**：`GroupPluginStorage` 读写须在 metadata 声明键；与 [command_limits](../../common/command_limits/README.md) 一样纳入能力总览。
- **冷却**：`is_command_cooldown_ready` / `refresh_command_cooldown` 的 key 为 `cmd_limit:{command_id}`。
- 配置里的 `praise_cd_sec` 为 0 时不做 CD 检查。
- 本插件只读用户口令，不接 [message_scrub](../../common/message_scrub/README.md)；复读/做梦类才需要。

### 怎样算成功

1. 重启 Bot 后，群里 **牛牛帮助** 能看到「牛牛赞我」插件（若 help 有开关，确认本群已开启）。
2. 发 **牛牛赞我**，Bot 回复带累计赞数。
3. 连续发送应触发冷却提示（默认 60 秒）。
4. 发 **牛牛赞榜** 能看到排行。
5. 控制台改 `praise_reply` 保存后，再赞一次文案立即变化。

---

## 6、拆文件与注册方式（小结）

上面把 handler 写在 `handlers.py`，`__init__.py` 里用 `bind_alias_handlers` 注册。  
也可以直接在 `__init__.py` 里 `@praise_cmd.handle()`，但教程刻意练习 **入口轻量、业务外置**，与 [插件结构](structure.md) 一致。

口令型优先 [plugin_sdk](../../architecture/core-devx-roadmap.md#p1--plugin_sdk) 的 `group_command`；选型见 [Matcher 决策树](../../skills/pallas-plugin-development/references/02-matchers-decision.md)。

---

## 7、测试

`store.py` 里的纯函数最适合单测，不必每次起真 Bot；`GroupPluginStorage` 集成测法见 `tests/features/test_plugin_storage.py`。

在 `tests/plugins/praise_me/test_store.py`（贡献主仓时）：

```python
from src.plugins.praise_me.store import add_praise, top_praisers


def test_add_praise_increments():
    counts = {}
    assert add_praise(counts, "10001") == 1
    assert add_praise(counts, "10001") == 2
    assert add_praise(counts, "10002") == 1


def test_top_praisers_order():
    counts = {"a": 3, "b": 9, "c": 1}
    assert top_praisers(counts, limit=2) == [("b", 9), ("a", 3)]
```

站点插件阶段可把 `store.py` 临时拷到可 import 路径，或只在本机手动测群消息。  
合并主仓前务必：

```bash
uv run ruff check src/
uv run ruff format --check src/
uv run pytest tests/plugins/praise_me/
```

---

## 8、用户向文档

在 `docs/plugins/praise_me/README.md` 写部署者能看懂的一页（可复制 [TEMPLATE.md](../../plugins/TEMPLATE.md)）：

```markdown
# 牛牛赞我（`praise_me`）

群内给牛牛点赞并查看本群赞榜。

## 用户命令

| 口令 | 场景 | 说明 |
| --- | --- | --- |
| 牛牛赞我 | 群内 | 点赞，有冷却 |
| 牛牛赞榜 | 群内 | Top 5 与本人赞数 |

## 命令权限

| 命令 ID | 默认等级 |
| --- | --- |
| `praise_me.praise` | everyone |
| `praise_me.rank` | everyone |

## 配置

| 键 | 默认 | 说明 |
| --- | --- | --- |
| enable | true | 是否启用 |
| praise_cd_sec | 60 | 点赞冷却（秒） |
| praise_reply | （见 config.py） | 成功回复，支持 `{total}` |

## 实现

`local/plugins/praise_me/` 或 `src/plugins/praise_me/`
```

并在 [plugins/README.md](../../plugins/README.md) 索引里加一行。

---

## 9、提交前 checklist

对照 [golden plugin checklist](../../skills/pallas-plugin-development/references/08-golden-plugin-checklist.md)：

- [ ] `__init__.py` 短；`config` / `store` / `handlers` 已拆分
- [ ] WebUI 热重载；handler 内 `get_config()`
- [ ] 命令 ID 与 cmd_perm、matcher、`command_limits` 一致
- [ ] 群/用户结构化状态：`extra["plugin_storage"]` + `GroupPluginStorage`（Cookbook §3–§4）
- [ ] `usage` / `trigger_condition` 无写死权限句
- [ ] 大文件/缓存才用 `plugin_data_dir` / `resource_dir`
- [ ] 有最小单测（至少 `store` 纯函数）
- [ ] `docs/plugins/praise_me/README.md` 已写

提交流程：[贡献与提交流程](../workflow.md)。

---

## 10、还可以怎么增强

按兴趣选做，不必一次做完：

| 方向 | 提示 |
| --- | --- |
| 私聊查赞 | 再加 `on_command` + `private_message_permission_for_command` |
| 全服榜 | 用 `src.foundation.db` 做持久化，或 deploy 级 `plugin_storage` |
| 帮助图样式 | 保持 `menu_data` 与 metadata 同步即可 |
| 贡献主仓 | 挪到 `src/plugins/praise_me/`，PR 附测试与插件文档 |
| 官方扩展包 | 4.0 玩法类可走扩展仓 + `uv sync --extra plugins-*` |

---

## 延伸阅读

| 文档 | 内容 |
| --- | --- |
| [插件开发入门](getting-started.md) | 最小骨架速览 |
| [插件结构](structure.md) | 目录拆分原则 |
| [插件进阶](advanced.md) | cmd_perm、分片、AI 等横切 |
| [插件开发 Skill · 分章](../../skills/pallas-plugin-development/SKILL.md) | Matcher、scrub、测试专题 |
| [cmd_perm](../../common/cmd_perm/README.md) | 权限矩阵与帮助文案细则 |
