from __future__ import annotations

import pytest

from src.foundation.db import (
    CONTEXT_REPO_REGISTRY,
    ensure_backend_registered,
    register_backend,
)


@pytest.fixture(autouse=True)
def clear_registered_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.foundation.db as db_mod

    monkeypatch.setattr(db_mod, "_backends_registered", set())
    CONTEXT_REPO_REGISTRY.clear()
    db_mod.MESSAGE_REPO_REGISTRY.clear()
    db_mod.BLACKLIST_REPO_REGISTRY.clear()
    db_mod.INIT_DB_REGISTRY.clear()


def test_ensure_backend_registered_only_registers_active_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_BACKEND", "postgresql")

    backend = ensure_backend_registered()

    assert backend == "postgresql"
    assert "postgresql" in CONTEXT_REPO_REGISTRY
    assert "mongodb" not in CONTEXT_REPO_REGISTRY
