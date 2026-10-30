"""Bot 内部 IPC 凭据：由共享根密钥按固定用途标签派生，仅用于进程间登记/删除。

根密钥复用 `data/pallas_console/session_secret.bin`（控制台会话密钥），每次调用读取当前值，
因此既有根密钥轮换会即时生效；不新增凭据库，也不把根密钥下发给 AI 或浏览器。
"""

from __future__ import annotations

import hashlib
import hmac
from typing import TYPE_CHECKING

from pallas.core.foundation.paths import plugin_data_dir
from pallas.core.foundation.secret_file import SecretFileError, ensure_private_bytes

if TYPE_CHECKING:
    from pathlib import Path

INTERNAL_TOKEN_HEADER = "X-Pallas-Internal-Token"
PURPOSE_AI_TASK_REGISTRATION = "ai-task-registration"
PURPOSE_MAIBOT_CONTROL_V1 = "maibot-control-v1"

_SESSION_SECRET_NAME = "session_secret.bin"
_LABEL_PREFIX = "pallas-internal-v1:"
_MIN_SECRET_BYTES = 32


def session_secret_path() -> Path:
    return plugin_data_dir("pallas_console", create=False) / _SESSION_SECRET_NAME


def load_root_secret() -> bytes:
    """读取共享根密钥；缺失时原子不覆盖地生成并读取赢家。

    非缺失的读取错误（权限、损坏）失败关闭并抛出，不重置密钥。
    """
    return ensure_private_bytes(session_secret_path(), length=32, min_bytes=_MIN_SECRET_BYTES)


def derive_internal_token(purpose: str) -> str:
    label = str(purpose or "").strip()
    if not label:
        return ""
    try:
        secret = load_root_secret()
    except SecretFileError:
        return ""
    if len(secret) < _MIN_SECRET_BYTES:
        return ""
    return hmac.new(secret, f"{_LABEL_PREFIX}{label}".encode(), hashlib.sha256).hexdigest()


def verify_internal_token(purpose: str, presented: str | None) -> bool:
    expected = derive_internal_token(purpose)
    given = str(presented or "").strip()
    if not expected or not given or not given.isascii():
        return False
    return hmac.compare_digest(expected, given)


def internal_auth_headers(purpose: str) -> dict[str, str]:
    token = derive_internal_token(purpose)
    if not token:
        return {}
    return {INTERNAL_TOKEN_HEADER: token}
