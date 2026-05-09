"""Pallas 控制台（/pallas）与协议端管理页共用的鉴权。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import string
import sys
import time
from contextvars import ContextVar
from pathlib import Path  # noqa: TC003
from typing import Any

from nonebot import logger

from src.common.paths import plugin_data_dir

_http_request_var: ContextVar[Any] = ContextVar("_pallas_http_request", default=None)

_AUTH_STATE = "auth_state.json"
_DEFAULT_LOGIN_PASSWORD_FILE = "default_login_password.txt"
_SESSION_SECRET = "session_secret.bin"
SESSION_COOKIE_NAME = "pallas_console_session"
SESSION_TTL_SEC = 72 * 3600
_announced_default_password_auth_path: str | None = None
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 64


def console_auth_dir() -> Path:
    return plugin_data_dir("pallas_console")


def auth_state_path() -> Path:
    return console_auth_dir() / _AUTH_STATE


def default_login_password_path() -> Path:
    """自动生成的默认口令明文副本路径；用户修改口令后应不存在。"""
    return console_auth_dir() / _DEFAULT_LOGIN_PASSWORD_FILE


def session_secret_path() -> Path:
    return console_auth_dir() / _SESSION_SECRET


def invalidate_shared_console_login_token_cache() -> None:
    """保留旧名：口令哈希变更后使内存缓存失效（当前无长期缓存）。"""


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _write_default_login_password_plain(plain: str) -> None:
    _atomic_write_text(default_login_password_path(), f"{str(plain or '').strip()}\n")


def _read_default_login_password_plain() -> str | None:
    p = default_login_password_path()
    if not p.is_file():
        return None
    try:
        s = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return s or None


def _unlink_default_login_password_plain() -> None:
    p = default_login_password_path()
    try:
        p.unlink(missing_ok=True)
    except TypeError:
        if p.is_file():
            p.unlink()


def _load_session_secret() -> bytes:
    p = session_secret_path()
    if p.is_file() and p.stat().st_size >= 32:
        return p.read_bytes()
    key = secrets.token_bytes(32)
    _atomic_write_bytes(p, key)
    return key


def _hash_password(plain: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        plain.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )


def _load_auth_state() -> dict[str, Any] | None:
    p = auth_state_path()
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    ph = str(raw.get("password_hash_hex", "") or "").strip()
    ps = str(raw.get("password_salt_hex", "") or "").strip()
    if not ph or not ps:
        return None
    if not all(c in string.hexdigits for c in ph) or not all(c in string.hexdigits for c in ps):
        return None
    return raw


def _write_auth_state(password_hash: bytes, password_salt: bytes) -> None:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    prev = _load_auth_state()
    generated = str((prev or {}).get("generated_at", "") or "").strip() or now
    state = {
        "v": 1,
        "password_hash_hex": password_hash.hex(),
        "password_salt_hex": password_salt.hex(),
        "generated_at": generated,
        "updated_at": now,
    }
    _atomic_write_text(auth_state_path(), json.dumps(state, ensure_ascii=False, indent=2))


def verify_console_password(plain: str) -> bool:
    st = _load_auth_state()
    if not st:
        return False
    try:
        salt = bytes.fromhex(str(st["password_salt_hex"]))
        expected = bytes.fromhex(str(st["password_hash_hex"]))
    except ValueError:
        return False
    got = _hash_password(str(plain or ""), salt)
    return hmac.compare_digest(got, expected)


def set_console_password_plain(new_plain: str, *, keep_default_password_plaintext: bool = False) -> None:
    s = str(new_plain or "")
    if not s:
        raise ValueError("口令不能为空")
    if not keep_default_password_plaintext:
        _unlink_default_login_password_plain()
    salt = secrets.token_bytes(16)
    pw_hash = _hash_password(s, salt)
    _write_auth_state(pw_hash, salt)
    invalidate_console_sessions()


def _materialize_auth_state() -> tuple[str | None, bool]:
    """返回 (若需打印给管理员的明文口令, 是否本次随机生成)。"""
    if _load_auth_state():
        return None, False
    chosen = secrets.token_urlsafe(18)
    set_console_password_plain(chosen, keep_default_password_plaintext=True)
    _write_default_login_password_plain(chosen)
    return chosen, True


def prime_shared_console_login() -> None:
    global _announced_default_password_auth_path
    _load_session_secret()
    plain, rnd = _materialize_auth_state()
    auth_path = str(auth_state_path().resolve())
    if plain is not None and rnd:
        logger.info("Pallas 控制台鉴权已初始化，状态文件: {}", auth_state_path())
        logger.success("Pallas 默认口令: {}", plain)
        try:
            sys.stderr.write(f"[Pallas] 默认口令: {plain}\n")
            sys.stderr.flush()
        except OSError:
            pass
        _announced_default_password_auth_path = auth_path
    else:
        boot = _read_default_login_password_plain()
        if boot and not verify_console_password(boot):
            _unlink_default_login_password_plain()
        elif boot:
            if _announced_default_password_auth_path != auth_path:
                logger.success("Pallas 默认口令: {}", boot)
                try:
                    sys.stderr.write(f"[Pallas] 默认口令: {boot}\n")
                    sys.stderr.flush()
                except OSError:
                    pass
            _announced_default_password_auth_path = auth_path


def is_console_auth_configured() -> bool:
    return _load_auth_state() is not None


def invalidate_console_sessions() -> None:
    """口令变更后轮换会话密钥，使已签发令牌全部失效。"""
    _atomic_write_bytes(session_secret_path(), secrets.token_bytes(32))


def mint_session_token() -> str:
    """签发短期会话令牌（非 HttpOnly，可放 X-Pallas-Token）。"""
    secret = _load_session_secret()
    exp = int(time.time()) + SESSION_TTL_SEC
    payload = json.dumps({"v": 1, "exp": exp}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    pl_b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    sig = hmac.new(secret, pl_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    return f"v1.{pl_b64}.{sig_b64}"


def verify_session_token(token: str | None) -> bool:
    t = (token or "").strip()
    if not t.startswith("v1.") or t.count(".") != 2:
        return False
    _, pl_b64, sig_b64 = t.split(".", 2)
    secret = _load_session_secret()
    expect_sig = hmac.new(secret, pl_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        got_sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
    except (ValueError, binascii.Error, TypeError):
        return False
    if not hmac.compare_digest(expect_sig, got_sig):
        return False
    try:
        raw = base64.urlsafe_b64decode(pl_b64 + "=" * (-len(pl_b64) % 4))
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(obj, dict) or int(obj.get("exp", 0) or 0) < int(time.time()):
        return False
    return int(obj.get("v", 0) or 0) == 1


def extract_session_from_request(
    *,
    cookies: dict[str, str],
    header_token: str | None,
    query_token: str | None,
    cookie_token: str | None = None,
) -> str | None:
    """优先级：专用 Cookie → 各端 Header/Query/Cookie 槽位中的会话串。"""
    for k in (SESSION_COOKIE_NAME,):
        v = (cookies.get(k) or "").strip()
        if v and verify_session_token(v):
            return v
    for v in (header_token, query_token, cookie_token):
        s = (v or "").strip()
        if s and verify_session_token(s):
            return s
    return None


def set_shared_console_login_token(new_plain: str) -> None:
    """保留旧函数名：写入新口令哈希。"""
    set_console_password_plain(new_plain)


def get_shared_console_login_token() -> str:
    """已废弃：磁盘不再存明文。返回空字符串，请改用 verify_session_token / mint_session_token。"""
    return ""


def current_http_request() -> Any:
    return _http_request_var.get()


def install_pallas_http_request_context_middleware(app: Any) -> None:
    """每个请求绑定 Starlette Request，供协议端 / 控制台在无显式 Request 参数时做会话校验。"""
    if getattr(app.state, "_pallas_http_ctx_mw", False):
        return
    app.state._pallas_http_ctx_mw = True
    from starlette.requests import Request  # noqa: TC002

    @app.middleware("http")
    async def _pallas_http_request_context(request: Request, call_next):  # noqa: ARG001
        tok = _http_request_var.set(request)
        try:
            return await call_next(request)
        finally:
            _http_request_var.reset(tok)
