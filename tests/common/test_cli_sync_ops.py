from __future__ import annotations

from pallas.console.cli.sync_ops import expand_sync_extras, sync_alias_notes


def test_expand_sync_extras_aliases():
    assert expand_sync_extras([], deploy_full=True) == []
    assert expand_sync_extras(["coord-redis"], deploy_all=True) == ["coord-redis"]


def test_sync_alias_notes_warn_for_legacy_deploy_aliases():
    notes = sync_alias_notes(deploy_full=True, deploy_all=True, extras=["deploy-all"])
    assert any("deploy-full" in note for note in notes)
    assert any("deploy-all" in note for note in notes)
