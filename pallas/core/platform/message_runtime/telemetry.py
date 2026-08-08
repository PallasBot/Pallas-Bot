from __future__ import annotations

import hashlib
import json
import time
from threading import Lock
from typing import TYPE_CHECKING

from pallas.core.foundation.fs_lock import interprocess_file_lock

if TYPE_CHECKING:
    from pathlib import Path

    from .shadow import ShadowRecord


class ExperimentTelemetryWriter:
    def __init__(
        self,
        path: Path,
        *,
        agreement_sample_rate: int = 1_000,
        retention_sec: int = 7 * 24 * 60 * 60,
    ) -> None:
        self.path = path
        self._agreement_sample_rate = max(1, agreement_sample_rate)
        self._retention_sec = max(1, retention_sec)
        self._pending: list[ShadowRecord] = []
        self._pending_lock = Lock()

    def record(self, record: ShadowRecord) -> None:
        if record.kind != "agreement" or self._sample_agreement(record.ingress_id):
            with self._pending_lock:
                self._pending.append(record)

    def flush(self) -> None:
        with self._pending_lock:
            if not self._pending:
                return
            pending, self._pending = self._pending, []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with interprocess_file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
                with self.path.open("a", encoding="utf-8") as file:
                    for record in pending:
                        file.write(json.dumps(record.as_dict(), separators=(",", ":")) + "\n")
        except OSError:
            with self._pending_lock:
                self._pending[:0] = pending
            raise

    def prune(self, *, now: int | None = None) -> None:
        if not self.path.is_file():
            return
        cutoff = int(now if now is not None else time.time()) - self._retention_sec
        with interprocess_file_lock(self.path.with_suffix(self.path.suffix + ".lock")):
            rows = self._retained_rows(cutoff)
            if not rows:
                self.path.unlink(missing_ok=True)
                return
            body = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
            self.path.write_text(body, encoding="utf-8")

    def _sample_agreement(self, ingress_id: str) -> bool:
        digest = hashlib.sha256(ingress_id.encode()).digest()
        return int.from_bytes(digest[:8]) % self._agreement_sample_rate == 0

    def _retained_rows(self, cutoff: int) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and int(row.get("ts") or 0) > cutoff:
                rows.append(row)
        return rows
