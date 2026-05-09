from __future__ import annotations

import pytest


def test_empty_password_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from src.common import pallas_console_login as m

    monkeypatch.setattr(m, "console_auth_dir", lambda: tmp_path / "pc")
    with pytest.raises(ValueError, match="口令不能为空"):
        m.set_console_password_plain("")
    with pytest.raises(ValueError, match="口令不能为空"):
        m.set_shared_console_login_token("")


def test_password_verify_and_session(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from src.common import pallas_console_login as m

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
    from src.common.pallas_console_login import get_shared_console_login_token

    assert get_shared_console_login_token() == ""


def test_default_password_plain_file_and_clear_on_user_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from src.common import pallas_console_login as m

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
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from src.common import pallas_console_login as m

    root = tmp_path / "pc"
    monkeypatch.setattr(m, "console_auth_dir", lambda: root)
    m.set_console_password_plain("real-secret")
    plain_path = m.default_login_password_path()
    plain_path.write_text("wrong-old\n", encoding="utf-8")
    m.prime_shared_console_login()
    assert not plain_path.is_file()
