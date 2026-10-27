from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import stat
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pallas.core.foundation.fs_lock import interprocess_file_lock
from pallas.core.foundation.paths import DATA_ROOT
from pallas.core.foundation.secret_file import SecretFileError, write_private_bytes

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

MCP_KEY_PREFIX = "pmcp_"
SCOPES = frozenset({"arknights:read", "prts:read"})
DEFAULT_SCOPES = SCOPES
MAX_KEYS = 256
MAX_STORE_BYTES = 256 * 1024
_KEY_RE = re.compile(r"pmcp_[A-Za-z0-9_-]{43}\Z")
_KEY_ID_RE = re.compile(r"[0-9a-f]{16}\Z")


class CredentialStoreError(RuntimeError):
    """The private MCP credential store is unavailable or malformed."""


@dataclass(frozen=True)
class Credential:
    id: str
    label: str
    scopes: frozenset[str]
    created_at: str


def _valid_row(row: object) -> bool:
    if not isinstance(row, dict) or set(row) != {"id", "label", "hash", "scopes", "created_at"}:
        return False
    key_id = row.get("id")
    label = row.get("label")
    digest = row.get("hash")
    scopes = row.get("scopes")
    return (
        isinstance(key_id, str)
        and _KEY_ID_RE.fullmatch(key_id) is not None
        and isinstance(label, str)
        and len(label) <= 80
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        and isinstance(scopes, list)
        and bool(scopes)
        and all(isinstance(scope, str) and scope in SCOPES for scope in scopes)
        and len(set(scopes)) == len(scopes)
        and isinstance(row.get("created_at"), str)
    )


class CredentialStore:
    def __init__(self, data_root: Path | None = None):
        self.directory = (data_root or DATA_ROOT) / "pallas_mcp"
        self.file_path = self.directory / "tokens.json"
        self.lock_path = self.directory / "tokens.lock"

    def _prepare_directory(self) -> None:
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not stat.S_ISDIR(self.directory.lstat().st_mode):
                raise CredentialStoreError("MCP credential directory is not a directory")
            self.directory.chmod(0o700)
        except OSError as exc:
            raise CredentialStoreError("MCP credential directory is unavailable") from exc

    @contextmanager
    def _lock(self):
        self._prepare_directory()
        try:
            with interprocess_file_lock(self.lock_path):
                self.lock_path.chmod(0o600)
                yield
        except OSError as exc:
            raise CredentialStoreError("MCP credential store is unavailable") from exc

    def _read_rows(self) -> list[dict[str, object]]:
        try:
            file_stat = self.file_path.lstat()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise CredentialStoreError("MCP credential store is unreadable") from exc
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_STORE_BYTES:
            raise CredentialStoreError("MCP credential store is invalid or too large")
        try:
            self.file_path.chmod(0o600)
            value = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CredentialStoreError("MCP credential store is malformed") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "keys"}
            or value.get("v") != 1
            or not isinstance(value.get("keys"), list)
        ):
            raise CredentialStoreError("MCP credential store is malformed")

        rows = value["keys"]
        if len(rows) > MAX_KEYS:
            raise CredentialStoreError("MCP credential store exceeds its key limit")
        for row in rows:
            if not _valid_row(row):
                raise CredentialStoreError("MCP credential store is malformed")
        if len({row["id"] for row in rows}) != len(rows):
            raise CredentialStoreError("MCP credential store contains duplicate ids")
        return rows

    def _write_rows(self, rows: list[dict[str, object]]) -> None:
        payload = json.dumps({"v": 1, "keys": rows}, ensure_ascii=False, separators=(",", ":"))
        try:
            write_private_bytes(self.file_path, payload.encode("utf-8"), overwrite=True)
        except SecretFileError as exc:
            raise CredentialStoreError("MCP credential store could not be written") from exc

    @staticmethod
    def _digest(secret: str) -> str:
        return hashlib.sha256(secret.encode("ascii")).hexdigest()

    def issue(
        self,
        *,
        label: str = "",
        scopes: Iterable[str] | None = None,
    ) -> tuple[str, str]:
        label = str(label or "").strip()
        if len(label) > 80:
            raise ValueError("MCP key label must be at most 80 characters")
        selected = DEFAULT_SCOPES if scopes is None else frozenset(scopes)
        if not selected or not selected <= SCOPES:
            raise ValueError("MCP key scopes must be a non-empty subset of the read scopes")

        secret = f"{MCP_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        key_id = secrets.token_hex(8)
        row: dict[str, object] = {
            "id": key_id,
            "label": label,
            "hash": self._digest(secret),
            "scopes": sorted(selected),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        try:
            with self._lock():
                rows = self._read_rows()
                if len(rows) >= MAX_KEYS:
                    raise CredentialStoreError("MCP credential store is full")
                rows.append(row)
                self._write_rows(rows)
        except OSError as exc:
            raise CredentialStoreError("MCP credential store is unavailable") from exc
        return secret, key_id

    def authenticate(self, secret: str | None) -> Credential | None:
        if not isinstance(secret, str) or not _KEY_RE.fullmatch(secret):
            return None
        try:
            digest = self._digest(secret)
            with self._lock():
                rows = self._read_rows()
        except (CredentialStoreError, OSError, UnicodeError, ValueError):
            return None
        for row in rows:
            stored_hash = row["hash"]
            if isinstance(stored_hash, str) and hmac.compare_digest(stored_hash, digest):
                return Credential(
                    id=str(row["id"]),
                    label=str(row["label"]),
                    scopes=frozenset(row["scopes"]),
                    created_at=str(row["created_at"]),
                )
        return None

    def list(self) -> list[dict[str, object]]:
        try:
            with self._lock():
                rows = self._read_rows()
        except OSError as exc:
            raise CredentialStoreError("MCP credential store is unavailable") from exc
        return [
            {
                "id": row["id"],
                "label": row["label"],
                "scopes": list(row["scopes"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def revoke(self, key_id: str) -> bool:
        try:
            with self._lock():
                rows = self._read_rows()
                remaining = [row for row in rows if row["id"] != key_id]
                if len(remaining) == len(rows):
                    return False
                self._write_rows(remaining)
                return True
        except OSError as exc:
            raise CredentialStoreError("MCP credential store is unavailable") from exc
