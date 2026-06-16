from __future__ import annotations

from src.console.cli.sync_ops import expand_sync_extras


def test_expand_sync_extras_aliases():
    assert expand_sync_extras([], deploy_full=True) == ["deploy-full"]
    assert expand_sync_extras(["plugins-duel"], deploy_all=True) == ["deploy-all", "plugins-duel"]
