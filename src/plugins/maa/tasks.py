from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from src.foundation.command_prefix import matches_text_prefix, peel_text_prefix

# MAA 客户端常见为 32 位十六进制；协议示例亦可能出现标准 UUID
_DEVICE_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
_DEVICE_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def normalize_device_id(raw: str) -> str | None:
    """统一为 32 位小写 hex，便于与 MAA 轮询体对齐。"""
    s = (raw or "").strip()
    if not s:
        return None
    compact = s.lower().replace("-", "")
    if _DEVICE_HEX32_RE.fullmatch(compact):
        return compact
    if _DEVICE_UUID_RE.fullmatch(s.lower()):
        return compact
    return None


def parse_bind_command_args(text: str) -> tuple[str, str]:
    """解析绑定参数：设备标识符与可选别名。

    兼容误写「牛牛绑定MAA设备 <id>」时 NoneBot 将「设备」吃进参数的情况。
    """
    line = (text or "").strip()
    if not line:
        return "", ""
    tokens = line.split()
    if tokens and tokens[0] == "设备":
        tokens = tokens[1:]
    if not tokens:
        return "", ""
    device_part = tokens[0]
    alias_part = " ".join(tokens[1:]).strip()
    return device_part, alias_part


def bind_device_id_error(raw: str, qq: str) -> str | None:
    """校验绑定参数；通过则返回 None。"""
    text = (raw or "").strip()
    if not text:
        return "用法：牛牛绑定MAA <设备标识符> [别名]\n请复制 MAA「远程控制」中的「设备标识符（只读）」。"
    if text == (qq or "").strip():
        return "你填写的是用户标识符（QQ 号）。请填写 MAA 设置里「设备标识符（只读）」那一项（32 位十六进制）。"
    if text == "设备":
        return (
            "不要把「设备」当作标识符。请发：牛牛绑定MAA <32位设备标识符> [别名]\n"
            "（也可发：牛牛绑定MAA设备 <标识符> [别名]）"
        )
    if normalize_device_id(text) is None:
        return "设备标识符格式不正确，请从 MAA「远程控制」完整复制「设备标识符（只读）」。"
    return None


# 协议支持的 type，见 https://docs.maa.plus/zh-cn/protocol/remote-control-schema.html
LINK_START_SUBTYPES = frozenset({
    "LinkStart-Base",
    "LinkStart-WakeUp",
    "LinkStart-Combat",
    "LinkStart-Recruiting",
    "LinkStart-Mall",
    "LinkStart-Mission",
    "LinkStart-AutoRoguelike",
    "LinkStart-Reclamation",
})

STAGE_SETTING_MAX = 4

# 远控仅文档化 Settings-Stage1；勿下发 Stage2~4 / FightEnable
SETTINGS_STAGE_REMOTE = "Settings-Stage1"

SETTINGS_TYPES = frozenset({
    "Settings-ConnectionAddress",
    SETTINGS_STAGE_REMOTE,
})

COMBAT_COMMAND_PHRASE = "牛牛作战"
# TODO：MAA 远控 LinkStart-Combat 在含「剩余理智」等辅助 FightTask 时失败；官方合并 PR 后改回 LinkStart-Combat
COMBAT_COMMAND_TASK_TYPE = "LinkStart"
COMBAT_PREP_TASK_TYPES = frozenset({"LinkStart-Combat"})

TOOLBOX_TYPES = frozenset({
    "Toolbox-GachaOnce",
    "Toolbox-GachaTenTimes",
})

IMMEDIATE_TYPES = frozenset({
    "CaptureImageNow",
    "StopTask",
    "HeartBeat",
})

# 下发这些 type 时不再自动追加截图任务
TASK_TYPES_WITHOUT_AUTO_SCREENSHOT = IMMEDIATE_TYPES | frozenset({"CaptureImage"}) | SETTINGS_TYPES

# 维护者：LinkStart-* 子项不含唤醒；游戏未在主界面时 MAA 易 TaskChainError。
# 牛牛不自动前置 LinkStart-WakeUp。截图/心跳/停止见 IMMEDIATE_TYPES。详见 docs/plugins/maa/README.md「维护者说明」。

# 远程控制协议允许下发的 type
ALLOWED_REMOTE_TASK_TYPES: frozenset[str] = (
    frozenset({"LinkStart", "CaptureImage"})
    | frozenset(LINK_START_SUBTYPES)
    | SETTINGS_TYPES
    | TOOLBOX_TYPES
    | IMMEDIATE_TYPES
)

MAA_RAW_TASK_PREFIX = "牛牛MAA任务"


@dataclass(frozen=True, slots=True)
class MaaControlCommandHelp:
    phrase: str
    task_type: str
    description: str


# 口令、MAA type、用途说明
MAA_CONTROL_COMMAND_HELPS: tuple[MaaControlCommandHelp, ...] = (
    MaaControlCommandHelp(
        "牛牛长草",
        "LinkStart",
        "按 MAA 当前勾选执行完整一键长草（全部子项，依本地配置）。",
    ),
    MaaControlCommandHelp(
        "牛牛唤醒",
        "LinkStart-WakeUp",
        "仅执行一键长草中的「唤醒」子项。",
    ),
    MaaControlCommandHelp(
        "牛牛作战",
        COMBAT_COMMAND_TASK_TYPE,
        "按 MAA 当前勾选执行作战相关任务（可先「牛牛设置关卡」）。",
    ),
    MaaControlCommandHelp(
        "牛牛公招",
        "LinkStart-Recruiting",
        "仅执行「公招」子项。",
    ),
    MaaControlCommandHelp(
        "牛牛基建",
        "LinkStart-Base",
        "仅执行「基建」子项（含换班、线索、制造等，依 MAA 基建配置）。",
    ),
    MaaControlCommandHelp(
        "牛牛信用商店",
        "LinkStart-Mall",
        "仅执行「信用商店」子项。",
    ),
    MaaControlCommandHelp(
        "牛牛领取奖励",
        "LinkStart-Mission",
        "仅执行「领取报酬」子项（日常/周常奖励等，依 MAA 配置）。",
    ),
    MaaControlCommandHelp(
        "牛牛肉鸽",
        "LinkStart-AutoRoguelike",
        "仅执行「自动肉鸽」子项（集成战略等，依 MAA 配置）。",
    ),
    MaaControlCommandHelp(
        "牛牛盐酸",
        "LinkStart-Reclamation",
        "仅执行「生息演算」子项（盐酸等，依 MAA 配置）。",
    ),
    MaaControlCommandHelp(
        "牛牛截图",
        "CaptureImage",
        "排队截取当前模拟器画面，完成后通过 QQ 回传。",
    ),
    MaaControlCommandHelp(
        "牛牛立刻截图",
        "CaptureImageNow",
        "立即截图（不等待前面排队任务结束）。",
    ),
    MaaControlCommandHelp(
        "牛牛停止",
        "StopTask",
        "请求结束当前正在执行的顺序任务。",
    ),
    MaaControlCommandHelp(
        "牛牛心跳",
        "HeartBeat",
        "查询当前顺序队列正在执行的任务 id（无任务则返回空）。",
    ),
    MaaControlCommandHelp(
        "牛牛单抽",
        "Toolbox-GachaOnce",
        "工具箱：公开招募单抽一次。",
    ),
    MaaControlCommandHelp(
        "牛牛十连",
        "Toolbox-GachaTenTimes",
        "工具箱：公开招募十连。",
    ),
)

COMMAND_TASK_MAP: dict[str, str] = {item.phrase: item.task_type for item in MAA_CONTROL_COMMAND_HELPS}

SETTINGS_CONNECTION_PREFIX = "牛牛设置连接 "
SETTINGS_STAGE_PREFIX = "牛牛设置关卡 "

_MAA_SETTINGS_COMMAND_HELPS: tuple[MaaControlCommandHelp, ...] = (
    MaaControlCommandHelp(
        "牛牛设置连接 <值>",
        "Settings-ConnectionAddress",
        "修改 MAA 连接地址（如模拟器 adb 地址）。",
    ),
    MaaControlCommandHelp(
        "牛牛设置关卡 <关卡…>",
        "Settings-Stage1",
        "设置作战主关卡并保存候选（最多 4 个；远控仅写入第 1 候选到 MAA，其余供「牛牛作战」前自动同步）。",
    ),
)


def _maa_help_table_section(title: str, items: tuple[MaaControlCommandHelp, ...]) -> str:
    rows = ["| 口令 | 说明 |", "|------|------|"]
    for item in items:
        phrase = item.phrase.replace("|", "｜")
        desc = item.description.replace("|", "｜")
        rows.append(f"| {phrase} | {desc} |")
    return f"### {title}\n\n" + "\n".join(rows)


def format_maa_plugin_usage_brief() -> str:
    """二级帮助页「插件内用法」简报。"""
    return "\n\n".join([
        "1. **私聊绑定**：牛牛绑定MAA <设备标识符> [别名]（设备 id 见 MAA「远程控制」）",
        "2. **MAA 配置**：「远程控制」填写上方对接地址；用户标识符填 QQ 号",
        "3. **远控口令**：牛牛长草、牛牛作战、牛牛公招等（须已绑定；**完整表**见下表第 2 条 → 功能详情）",
        "4. **多设备**（私聊）：牛牛MAA状态、牛牛切换MAA设备、牛牛MAA设备名、牛牛清空MAA队列",
    ])


def format_maa_control_commands_help() -> str:
    """三级「MAA 远控」详情：分组表格。"""
    sections = [
        _maa_help_table_section("长草", (MAA_CONTROL_COMMAND_HELPS[0],)),
        _maa_help_table_section(
            "子项（按 MAA 左侧勾选；作战可先牛牛设置关卡）",
            MAA_CONTROL_COMMAND_HELPS[1:9],
        ),
        _maa_help_table_section("截图与控制", MAA_CONTROL_COMMAND_HELPS[9:]),
        _maa_help_table_section("设置", _MAA_SETTINGS_COMMAND_HELPS),
    ]
    return "\n\n".join([
        "发送**完整一行**口令（须先私聊绑定）。子项口令不含唤醒，游戏宜在主界面。",
        *sections,
        "高级：牛牛MAA任务 <type> [params] → 见本插件「MAA 远控（原始 type）」详情。",
    ])


def format_maa_raw_task_types_help() -> str:
    common = "LinkStart、LinkStart-Combat、CaptureImage、Settings-Stage1、StopTask…"
    return "\n\n".join([
        "用法：牛牛MAA任务 <type> [params]",
        "Settings-* 须带 params；其余 type 勿带多余参数。",
        f"常用 type：{common}",
        "完整列表见协议文档；示例：牛牛MAA任务 Settings-Stage1 1-7",
    ])


@dataclass(frozen=True, slots=True)
class MaaTaskSpec:
    task_type: str
    params: str | None = None


def parse_stage_setting_values(raw: str) -> list[str] | None:
    """解析关卡候选，最多 4 项；`-` 表示留空。"""
    text = (raw or "").strip()
    if not text:
        return None
    parts = re.split(r"[,，\s]+", text)
    stages: list[str] = []
    for part in parts:
        if len(stages) >= STAGE_SETTING_MAX:
            break
        token = part.strip()
        if token in ("-", "—", "空"):
            stages.append("")
        elif token:
            stages.append(token)
    if not stages or not any(stages):
        return None
    return stages


def primary_stage_from_plan(stages: list[str]) -> str | None:
    for stage in stages:
        if stage:
            return stage
    return None


def build_stage_setting_specs(stages: list[str]) -> list[MaaTaskSpec]:
    """远控仅下发 Settings-Stage1。"""
    primary = primary_stage_from_plan(stages)
    if not primary:
        return []
    return [MaaTaskSpec(SETTINGS_STAGE_REMOTE, primary)]


def build_combat_prep_specs(stage_plan: list[str]) -> list[MaaTaskSpec]:
    return build_stage_setting_specs(stage_plan)


@lru_cache(maxsize=1)
def control_phrase_to_task_type() -> dict[str, str]:
    return {phrase.casefold(): task_type for phrase, task_type in COMMAND_TASK_MAP.items()}


def task_type_for_control_phrase(line: str) -> str | None:
    return control_phrase_to_task_type().get((line or "").strip().casefold())


def is_control_phrase_line(line: str) -> bool:
    return task_type_for_control_phrase(line) is not None


@lru_cache(maxsize=1)
def canonical_remote_task_types() -> dict[str, str]:
    return {t.casefold(): t for t in ALLOWED_REMOTE_TASK_TYPES}


def canonical_remote_task_type(raw: str) -> str | None:
    return canonical_remote_task_types().get((raw or "").strip().casefold())


def is_combat_control_command(command_line: str, specs: list[MaaTaskSpec]) -> bool:
    if (command_line or "").strip().casefold() == COMBAT_COMMAND_PHRASE.casefold():
        return True
    return any(s.task_type in COMBAT_PREP_TASK_TYPES for s in specs)


def expand_command_specs(
    specs: list[MaaTaskSpec],
    *,
    stage_plan: list[str],
    combat_auto_prepare: bool,
    command_line: str = "",
) -> list[MaaTaskSpec]:
    if not combat_auto_prepare or not is_combat_control_command(command_line, specs):
        return specs
    if any(s.task_type == SETTINGS_STAGE_REMOTE for s in specs):
        return specs
    prep = build_combat_prep_specs(stage_plan)
    if not prep:
        return specs
    return prep + specs


def build_task_payload(task_id: str, spec: MaaTaskSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": task_id, "type": spec.task_type}
    if spec.params is not None:
        payload["params"] = spec.params
    return payload


def parse_command_line(text: str) -> MaaTaskSpec | None:
    specs = parse_command_specs(text)
    if not specs:
        return None
    return specs[0]


def parse_command_specs(text: str) -> list[MaaTaskSpec] | None:
    """解析「牛牛长草」或「牛牛设置连接 xxx」类口令，可能返回多项。"""
    line = (text or "").strip()
    if not line:
        return None

    if matches_text_prefix(line, SETTINGS_CONNECTION_PREFIX):
        value = peel_text_prefix(line, SETTINGS_CONNECTION_PREFIX)
        if value:
            return [MaaTaskSpec("Settings-ConnectionAddress", value)]
        return None

    if matches_text_prefix(line, SETTINGS_STAGE_PREFIX):
        stages = parse_stage_setting_values(peel_text_prefix(line, SETTINGS_STAGE_PREFIX))
        if stages:
            return build_stage_setting_specs(stages)
        return None

    task_type = task_type_for_control_phrase(line)
    if task_type:
        return [MaaTaskSpec(task_type)]
    raw = parse_maa_raw_task(line)
    return [raw] if raw else None


def parse_maa_raw_task(text: str) -> MaaTaskSpec | None:
    """解析「牛牛MAA任务 <type> [params]」。"""
    line = (text or "").strip()
    if not matches_text_prefix(line, MAA_RAW_TASK_PREFIX):
        return None
    rest = peel_text_prefix(line, MAA_RAW_TASK_PREFIX)
    if not rest:
        return None
    parts = rest.split(maxsplit=1)
    raw_type = parts[0]
    params = parts[1].strip() if len(parts) > 1 else None
    task_type = canonical_remote_task_type(raw_type)
    if task_type is None:
        return None
    if task_type in SETTINGS_TYPES:
        if not params:
            return None
        return MaaTaskSpec(task_type, params)
    if params:
        return None
    return MaaTaskSpec(task_type)


def maa_raw_task_usage_error() -> str:
    allowed = ", ".join(sorted(ALLOWED_REMOTE_TASK_TYPES))
    return (
        "用法：牛牛MAA任务 <type> [params]\n"
        "示例：牛牛MAA任务 Settings-Stage1 1-7\n"
        "示例：牛牛MAA任务 LinkStart-Recruiting\n"
        f"可用 type：{allowed}"
    )


def maa_raw_task_validate(text: str) -> tuple[MaaTaskSpec | None, str | None]:
    """返回 (spec, error_message)。"""
    line = (text or "").strip()
    if not matches_text_prefix(line, MAA_RAW_TASK_PREFIX):
        return None, None
    rest = peel_text_prefix(line, MAA_RAW_TASK_PREFIX)
    if not rest:
        return None, maa_raw_task_usage_error()
    parts = rest.split(maxsplit=1)
    raw_type = parts[0]
    params = parts[1].strip() if len(parts) > 1 else None
    task_type = canonical_remote_task_type(raw_type)
    if task_type is None:
        return None, f"不支持的 type：{raw_type}\n{maa_raw_task_usage_error()}"
    if task_type in SETTINGS_TYPES:
        if not params:
            return None, f"{task_type} 需要 params，例如：牛牛MAA任务 {task_type} <值>"
        return MaaTaskSpec(task_type, params), None
    if params:
        return None, f"{task_type} 不需要 params，请去掉「{params}」"
    return MaaTaskSpec(task_type), None
