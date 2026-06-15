from __future__ import annotations

import pytest

from src.foundation.db.runtime import (
    is_mongodb_backend,
    is_postgresql_backend,
    normalize_db_backend_name,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mongodb", "mongodb"),
        ("mongo", "mongodb"),
        ("postgresql", "postgresql"),
        ("pg", "postgresql"),
        ("POSTGRES", "postgresql"),
    ],
)
def test_normalize_db_backend_name(raw: str, expected: str) -> None:
    assert normalize_db_backend_name(raw) == expected


def test_backend_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_BACKEND", "postgresql")
    assert is_postgresql_backend()
    assert not is_mongodb_backend()
