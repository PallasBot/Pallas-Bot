from __future__ import annotations

import __future__
import ast
import hashlib
import os
import re
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from pallas.product.agent_bridge import native_compat as compat


@pytest.fixture
def small_sources(tmp_path, monkeypatch):
    specs = []
    for name in ("utils.py", "runtime.py"):
        path = tmp_path / name
        path.write_text("original\n")
        specs.append(
            compat.SourcePatch(
                name,
                hashlib.sha256(b"original\n").hexdigest(),
                hashlib.sha256(b"patched\n").hexdigest(),
                (("original\n", "patched\n"),),
            )
        )
    monkeypatch.setattr(compat, "PATCHES", tuple(specs))
    return tmp_path


def test_patch_is_hash_checked_and_idempotent(small_sources):
    assert compat.native_compat_state(small_sources) == "original"
    assert compat.apply_native_compat(small_sources) == "patched"
    assert compat.apply_native_compat(small_sources) == "patched"
    assert compat.native_compat_state(small_sources) == "patched"
    assert not list(small_sources.glob(".pallas-compat-*"))


def test_patch_set_includes_only_the_authorized_startup_port_change():
    spec = next((spec for spec in compat.PATCHES if spec.relative_path == "src/common/message_server/server.py"), None)
    assert spec is not None
    assert len(spec.edits) == 1
    before, after = spec.edits[0]
    assert after.replace("            allow_reuse_addr=True,\n", "") == before


@pytest.mark.parametrize(
    "states",
    ["ooo", "oop", "opo", "opp", "poo", "pop", "ppo", "ppp"],
)
def test_only_known_patch_sets_can_apply_or_upgrade(small_sources, monkeypatch, states):
    spec = compat.SourcePatch(
        "src/common/message_server/server.py",
        hashlib.sha256(b"original\n").hexdigest(),
        hashlib.sha256(b"patched\n").hexdigest(),
        (("original\n", "patched\n"),),
    )
    target = small_sources / spec.relative_path
    target.parent.mkdir(parents=True)
    paths = [small_sources / "utils.py", small_sources / "runtime.py", target]
    contents = [b"patched\n" if state == "p" else b"original\n" for state in states]
    for path, content in zip(paths, contents, strict=True):
        path.write_bytes(content)
    monkeypatch.setattr(compat, "PATCHES", (*compat.PATCHES, spec))
    if states not in {"ooo", "ppo", "ppp"}:
        with pytest.raises(compat.NativeCompatError, match="partially patched"):
            compat.apply_native_compat(small_sources)
        assert [path.read_bytes() for path in paths] == contents
        return
    expected = {"ooo": "original", "ppo": "upgradeable", "ppp": "patched"}
    assert compat.native_compat_state(small_sources) == expected[states]
    assert compat.apply_native_compat(small_sources) == "patched"
    assert target.read_bytes() == b"patched\n"
    assert compat.native_compat_state(small_sources) == "patched"


@pytest.mark.parametrize("case", ["unknown", "mixed", "pin", "file_symlink", "parent_symlink"])
def test_invalid_source_or_path_does_not_modify_other_file(small_sources, tmp_path, case):
    if case == "unknown":
        (small_sources / "utils.py").write_text("unknown\n")
    elif case == "mixed":
        (small_sources / "utils.py").write_text("patched\n")
    elif case == "file_symlink":
        outside = tmp_path / "outside.py"
        outside.write_text("original\n")
        (small_sources / "utils.py").unlink()
        (small_sources / "utils.py").symlink_to(outside)
    root = small_sources
    if case == "parent_symlink":
        root = tmp_path / "linked"
        root.symlink_to(small_sources, target_is_directory=True)
    with pytest.raises(compat.NativeCompatError):
        compat.apply_native_compat(root, expected_pin="unknown" if case == "pin" else compat.NATIVE_PIN)
    assert (small_sources / "runtime.py").read_bytes() == b"original\n"


def test_write_failure_restores_both_original_sources(small_sources, monkeypatch):
    replace = compat.os.replace
    count = 0

    def fail_second(source, target):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError("synthetic replacement failure")
        replace(source, target)

    monkeypatch.setattr(compat.os, "replace", fail_second)
    with pytest.raises(OSError, match="synthetic"):
        compat.apply_native_compat(small_sources)
    assert compat.native_compat_state(small_sources) == "original"
    assert not list(small_sources.glob(".pallas-compat-*"))


@pytest.fixture
def native_nodes(tmp_path, monkeypatch):
    raw = os.environ.get("PALLAS_MAIBOT_PIN_SOURCE")
    if not raw:
        pytest.skip("set PALLAS_MAIBOT_PIN_SOURCE to the exact supported MaiBot source")
    root = tmp_path / "native"
    for spec in compat.PATCHES:
        target = root / spec.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(Path(raw) / spec.relative_path, target)
    compat.apply_native_compat(root)
    config = SimpleNamespace(
        bot=SimpleNamespace(nickname="牛牛", alias_names=["小牛"]),
        chat=SimpleNamespace(reply_timing=SimpleNamespace(inevitable_at_reply=True, mentioned_bot_reply=True)),
    )
    namespace = {
        "os": os,
        "re": re,
        "global_config": config,
        "get_bot_accounts": lambda platform: {"10001", "10002"},
        "_has_at_component_targeting_bot": lambda message, platform: False,
        "logger": SimpleNamespace(debug=lambda *args: None),
    }
    for relative, name in (
        (compat.PATCHES[0].relative_path, "is_mentioned_bot_in_message"),
        (compat.PATCHES[1].relative_path, "_update_message_trigger_state"),
    ):
        tree = ast.parse((root / relative).read_text())
        node = next(item for item in ast.walk(tree) if isinstance(item, ast.FunctionDef) and item.name == name)
        module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
        exec(compile(module, str(root / relative), "exec", flags=__future__.annotations.compiler_flag), namespace)
    monkeypatch.setenv(compat.MENTION_PLATFORM_ENV, "pallas-qq")
    namespace["native_root"] = root
    namespace["native_source"] = Path(raw)
    return namespace


def test_native_port_patch_accepts_time_wait_but_refuses_live_listener(native_nodes):
    import socket

    root = native_nodes["native_root"]
    source = native_nodes["native_source"]
    namespace = {}
    checker = source / "src/common/utils/port_checker.py"
    exec(compile(checker.read_text(), str(checker), "exec"), namespace)
    patched = root / "src/common/message_server/server.py"
    tree = ast.parse(patched.read_text())
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "assert_port_available"
    )
    expression = compile(ast.fix_missing_locations(ast.Expression(call)), str(patched), "eval")
    namespace["logger"] = SimpleNamespace(error=lambda *_a, **_k: None)

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        peer = socket.create_connection(("127.0.0.1", port))
        accepted, _ = listener.accept()
        accepted.close()
        assert peer.recv(1) == b""
        peer.close()
    assert namespace["check_port_available"]("127.0.0.1", port) is False
    namespace["self"] = SimpleNamespace(_host="127.0.0.1", _port=port)
    assert eval(expression, namespace) is None

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        namespace["self"]._port = listener.getsockname()[1]
        with pytest.raises(OSError, match="端口"):
            eval(expression, namespace)


def message(*, account="10001", at=False, mentioned=False, stale=False, platform="pallas-qq"):
    return SimpleNamespace(
        account_id=account,
        platform=platform,
        processed_plain_text="泰坦牛牛，请回应",
        message_info=SimpleNamespace(
            additional_config={
                compat.AUTHORITY_FIELD: {
                    "schema_version": 1,
                    "account_id": account,
                    "at_bot": at,
                    "is_mentioned": mentioned,
                }
            }
        ),
        message_segment=None,
        raw_message=None,
        is_at=stale,
        is_mentioned=stale,
    )


@pytest.mark.parametrize(
    "at,mentioned,expected",
    [
        (False, False, (False, False, 0.0)),
        (False, True, (True, False, 1.0)),
        (True, False, (True, True, 1.0)),
        (True, True, (True, True, 1.0)),
    ],
)
def test_native_authority_controls_both_positive_and_negative(native_nodes, at, mentioned, expected):
    assert native_nodes["is_mentioned_bot_in_message"](message(at=at, mentioned=mentioned)) == expected


def test_native_negative_clears_stale_flags_without_forcing_or_dropping_message(native_nodes):
    event = message(stale=True)
    forced = []
    instance = SimpleNamespace(_arm_forced_turn=lambda *args, **kwargs: forced.append(kwargs))
    native_nodes["_update_message_trigger_state"](instance, event)
    assert event.is_at is event.is_mentioned is False
    assert forced == []
    assert event.processed_plain_text == "泰坦牛牛，请回应"


def test_native_two_accounts_have_separate_authority(native_nodes):
    helper = native_nodes["is_mentioned_bot_in_message"]
    assert helper(message(account="10001", mentioned=True)) == (True, False, 1.0)
    assert helper(message(account="10002")) == (False, False, 0.0)


@pytest.mark.parametrize(
    "case", ["missing", "wrong_account", "unknown_account", "version", "version_bool", "numeric_flag"]
)
def test_native_invalid_authority_fails_closed(native_nodes, case):
    event = message()
    authority = event.message_info.additional_config[compat.AUTHORITY_FIELD]
    if case == "missing":
        event.message_info.additional_config.clear()
    elif case == "wrong_account":
        authority["account_id"] = "10002"
    elif case == "unknown_account":
        event.account_id = authority["account_id"] = "99999"
    elif case == "version":
        authority["schema_version"] = 2
    elif case == "version_bool":
        authority["schema_version"] = True
    else:
        authority["is_mentioned"] = 1
    with pytest.raises(ValueError, match="authoritative"):
        native_nodes["is_mentioned_bot_in_message"](event)


def test_native_unmanaged_behavior_is_unchanged(native_nodes, monkeypatch):
    helper = native_nodes["is_mentioned_bot_in_message"]
    assert helper(message(platform="another-platform")) == (True, False, 1.0)
    monkeypatch.delenv(compat.MENTION_PLATFORM_ENV)
    assert helper(message()) == (True, False, 1.0)


@pytest.mark.parametrize("platform,opt_in", [("another-platform", "pallas-qq"), ("pallas-qq", "")])
def test_runtime_preserves_native_stale_flags_outside_opt_in(native_nodes, monkeypatch, platform, opt_in):
    monkeypatch.setenv(compat.MENTION_PLATFORM_ENV, opt_in)
    event = message(platform=platform, stale=True)
    event.processed_plain_text = "ordinary background text"
    forced = []
    instance = SimpleNamespace(_arm_forced_turn=lambda *args, **kwargs: forced.append(kwargs))
    native_nodes["_update_message_trigger_state"](instance, event)
    assert event.is_at is event.is_mentioned is True
    assert len(forced) == 1
