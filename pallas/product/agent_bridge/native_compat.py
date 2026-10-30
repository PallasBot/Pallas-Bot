"""固定 MaiBot pin 的可校验提及与启动兼容补丁。"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

NATIVE_PIN = "062d45cf8bd4272ac57d7ec03fcf405e5a458211"
PATCH_ID = "pallas-account-mention-v1"
MENTION_PLATFORM_ENV = "PALLAS_MAIBOT_MENTION_PLATFORM"
AUTHORITY_FIELD = "pallas_mention_authority"
STARTUP_PATCH_PATH = "src/common/message_server/server.py"

_PORT_CHECK = (
    "        assert_port_available(\n"
    "            host=self._host,\n"
    "            port=self._port,\n"
    '            service_name="消息服务器",\n'
    "            logger=logger,\n"
    '            config_hint="maim_message.ws_server_port (config/bot_config.toml)",\n'
    "        )\n"
)

_AUTHORITY_BRANCH = """    if os.environ.get("PALLAS_MAIBOT_MENTION_PLATFORM") == platform:
        authority = add_cfg.get("pallas_mention_authority") if isinstance(add_cfg, dict) else None
        account_id = str(getattr(message, "account_id", "") or "")
        if (
            not isinstance(authority, dict)
            or authority.keys() != {"schema_version", "account_id", "at_bot", "is_mentioned"}
            or type(authority.get("schema_version")) is not int
            or authority["schema_version"] != 1
            or not isinstance(authority.get("account_id"), str)
            or not account_id
            or authority["account_id"] != account_id
            or account_id not in current_accounts
            or type(authority.get("at_bot")) is not bool
            or type(authority.get("is_mentioned")) is not bool
        ):
            raise ValueError("Invalid authoritative Pallas mention envelope")
        is_at = authority["at_bot"]
        is_mentioned = is_at or authority["is_mentioned"]
        timing = global_config.chat.reply_timing
        forced = (is_at and timing.inevitable_at_reply) or (is_mentioned and timing.mentioned_bot_reply)
        return is_mentioned, is_at, float(bool(forced))
"""


class NativeCompatError(RuntimeError):
    """目标版本、内容或路径不满足固定补丁合同。"""


@dataclass(frozen=True)
class SourcePatch:
    relative_path: str
    original_sha256: str
    patched_sha256: str
    edits: tuple[tuple[str, str], ...]


PATCHES = (
    SourcePatch(
        "src/chat/utils/utils.py",
        "8178a5d437b660acccc182c6922514b43e8732d11c2e968eedfd2a1cf066222c",
        "af4815b7e606a9ed6b65c4159f7a24e8f82acc11b9ff39d844e2ee44d0e6a181",
        (
            ("import asyncio\nimport random\n", "import asyncio\nimport os\nimport random\n"),
            (
                '    if isinstance(add_cfg, dict):\n        if add_cfg.get("at_bot") or add_cfg.get("is_mentioned"):\n',
                _AUTHORITY_BRANCH + "    if isinstance(add_cfg, dict):\n"
                '        if add_cfg.get("at_bot") or add_cfg.get("is_mentioned"):\n',
            ),
        ),
    ),
    SourcePatch(
        "src/maisaka/runtime.py",
        "04645e49c53f3f0e55563dddb9a6c8a5167efc545609afb33e36be9262a4234a",
        "90f64eadd628e0e64d4c8dfdbbe9240fa754c38e7982f267eba0884da325dd71",
        (
            (
                "        if detected_at:\n            message.is_at = True\n"
                "        if detected_mentioned:\n            message.is_mentioned = True\n",
                "        message.is_at = detected_at\n        message.is_mentioned = detected_mentioned\n",
            ),
        ),
    ),
    SourcePatch(
        STARTUP_PATCH_PATH,
        "a9de3aa2c1bb8f6ce5445aecfbe976df293b79f04476bf6fe032ad9e61cff162",
        "e66096d1a15f155902bc798c2c9ba034d4fdea1d2c88ce7ad5702f152143a060",
        ((_PORT_CHECK, _PORT_CHECK.replace("        )\n", "            allow_reuse_addr=True,\n        )\n")),),
    ),
)


def native_compat_state(instance_dir: Path, *, expected_pin: str = NATIVE_PIN) -> str:
    """只接受完整原版、完整补丁或已知的旧提及补丁集。"""
    _, originals = inspect_sources(instance_dir, expected_pin=expected_pin)
    states = [
        "original" if hashlib.sha256(content).hexdigest() == spec.original_sha256 else "patched"
        for spec, _, content, _ in originals
    ]
    if states == ["patched", "patched", "original"] and PATCHES[-1].relative_path == STARTUP_PATCH_PATH:
        return "upgradeable"
    if len(set(states)) != 1:
        raise NativeCompatError("MaiBot compatibility source is partially patched")
    return states[0]


def inspect_sources(instance_dir: Path, *, expected_pin: str) -> tuple[Path, list]:
    if expected_pin != NATIVE_PIN:
        raise NativeCompatError("MaiBot compatibility pin is not supported")
    root = instance_dir.absolute()
    if not root.is_dir() or root.resolve() != root:
        raise NativeCompatError("MaiBot compatibility root must be a real directory")
    sources = []
    for spec in PATCHES:
        relative = Path(spec.relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise NativeCompatError("MaiBot compatibility target escapes its root")
        path = root
        for part in relative.parts:
            path = path / part
            if path.is_symlink():
                raise NativeCompatError("MaiBot compatibility target cannot use symlinks")
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise NativeCompatError("MaiBot compatibility target is not a regular source file")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() not in {spec.original_sha256, spec.patched_sha256}:
            raise NativeCompatError("MaiBot compatibility source hash is unknown")
        sources.append((spec, path, content, stat.S_IMODE(path.stat().st_mode)))
    return root, sources


def stage_source(path: Path, content: bytes, mode: int) -> Path:
    fd, name = tempfile.mkstemp(prefix=".pallas-compat-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def apply_native_compat(instance_dir: Path, *, expected_pin: str = NATIVE_PIN) -> str:
    """所有文件先校验再替换；写入失败恢复原内容，未知混合态拒绝启动。"""
    state = native_compat_state(instance_dir, expected_pin=expected_pin)
    if state == "patched":
        return state
    _, sources = inspect_sources(instance_dir, expected_pin=expected_pin)
    staged: list[tuple[Path, Path, Path]] = []
    temporaries: list[Path] = []
    replaced: list[tuple[Path, Path]] = []
    try:
        for spec, path, original, mode in sources:
            if hashlib.sha256(original).hexdigest() == spec.patched_sha256:
                continue
            text = original.decode("utf-8")
            for before, after in spec.edits:
                if text.count(before) != 1:
                    raise NativeCompatError("MaiBot compatibility source pattern is ambiguous")
                text = text.replace(before, after, 1)
            patched = text.encode("utf-8")
            if hashlib.sha256(patched).hexdigest() != spec.patched_sha256:
                raise NativeCompatError("MaiBot compatibility patch output hash is unknown")
            backup = stage_source(path, original, mode)
            temporaries.append(backup)
            replacement = stage_source(path, patched, mode)
            temporaries.append(replacement)
            staged.append((path, replacement, backup))
        for path, replacement, backup in staged:
            replacement.replace(path)
            replaced.append((path, backup))
    except BaseException as exc:
        failures = []
        for path, backup in reversed(replaced):
            try:
                backup.replace(path)
            except OSError:
                failures.append(path)
        if failures:
            raise NativeCompatError("MaiBot compatibility patch failed and rollback is incomplete") from exc
        raise
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)
    return "patched"
