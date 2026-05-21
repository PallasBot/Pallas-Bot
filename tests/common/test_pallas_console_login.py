from __future__ import annotations

import shutil

import pytest


def test_empty_password_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from src.common.webui import console_login as m

    monkeypatch.setattr(m, "console_auth_dir", lambda: tmp_path / "pc")
    with pytest.raises(ValueError, match="口令不能为空"):
        m.set_console_password_plain("")
    with pytest.raises(ValueError, match="口令不能为空"):
        m.set_shared_console_login_token("")


def test_password_verify_and_session(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from src.common.webui import console_login as m

    monkeypatch.setattr(m, "console_auth_dir", lambda: tmp_path / "pc")
    m.set_console_password_plain("a")
    assert m.verify_console_password("a")
    assert not m.verify_console_password("b")
    assert m.is_console_auth_configured()
    tok = m.mint_session_token()
    assert m.verify_session_token(tok)
    assert not m.verify_session_token("v1.xxx.yyy")
    m.invalidate_console_sessions()
    assert not m.verify_session_token(tok)
    tok2 = m.mint_session_token()
    assert m.verify_session_token(tok2)


def test_get_shared_console_login_token_empty() -> None:
    from src.common.webui.console_login import get_shared_console_login_token

    assert get_shared_console_login_token() == ""


def test_default_password_plain_file_and_clear_on_user_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from src.common.webui import console_login as m

    root = tmp_path / "pc"
    monkeypatch.setattr(m, "console_auth_dir", lambda: root)

    m.prime_shared_console_login()
    plain_path = m.default_login_password_path()
    assert plain_path.is_file()
    boot = plain_path.read_text(encoding="utf-8").strip()
    assert m.verify_console_password(boot)

    m.prime_shared_console_login()
    assert plain_path.is_file()
    assert plain_path.read_text(encoding="utf-8").strip() == boot

    m.set_shared_console_login_token("user-chosen-password")
    assert not plain_path.is_file()
    assert m.verify_console_password("user-chosen-password")
    assert not m.verify_console_password(boot)


def test_orphan_default_password_file_removed_when_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from src.common.webui import console_login as m

    root = tmp_path / "pc"
    monkeypatch.setattr(m, "console_auth_dir", lambda: root)
    m.set_console_password_plain("real-secret")
    plain_path = m.default_login_password_path()
    plain_path.write_text("wrong-old\n", encoding="utf-8")
    m.prime_shared_console_login()
    assert not plain_path.is_file()


def test_prime_shared_console_login_announces_default_password_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from src.common.webui import console_login as m

    root = tmp_path / "pc_once"
    monkeypatch.setattr(m, "console_auth_dir", lambda: root)
    writes: list[str] = []

    def capture_write(s: str) -> int:
        writes.append(s)
        return len(s)

    monkeypatch.setattr(m.sys.stderr, "write", capture_write)
    m.prime_shared_console_login()
    m.prime_shared_console_login()
    hits = [w for w in writes if "[Pallas-Bot] 默认口令:" in w]
    assert len(hits) == 1


def test_prime_reannounces_default_password_when_auth_dir_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from src.common.webui import console_login as m

    m._announced_default_password_auth_path = None
    root1 = tmp_path / "pc_a"
    root1.mkdir()
    monkeypatch.setattr(m, "console_auth_dir", lambda: root1)
    writes: list[str] = []

    def capture_write(s: str) -> int:
        writes.append(s)
        return len(s)

    monkeypatch.setattr(m.sys.stderr, "write", capture_write)
    m.prime_shared_console_login()
    root2 = tmp_path / "pc_b"
    root2.mkdir()
    for name in ("auth_state.json", "default_login_password.txt"):
        src = root1 / name
        if src.is_file():
            shutil.copy2(src, root2 / name)
    monkeypatch.setattr(m, "console_auth_dir", lambda: root2)
    m.prime_shared_console_login()
    hits = [w for w in writes if "[Pallas-Bot] 默认口令:" in w]
    assert len(hits) == 2
