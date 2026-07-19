from __future__ import annotations

import concurrent.futures

from pallas.core.foundation.fs_lock import atomic_write_text, interprocess_file_lock


def test_atomic_write_text_unique_tmp(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"

    def write_one(i: int) -> None:
        with interprocess_file_lock(path.with_suffix(path.suffix + ".lock")):
            previous = path.read_text(encoding="utf-8") if path.is_file() else ""
            atomic_write_text(path, previous + f"{i}\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write_one, range(40)))

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 40
    assert not list(tmp_path.glob("*.tmp"))
