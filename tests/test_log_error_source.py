from packages.pb_webui.extended_api import _log_error_entry_matches_source


def test_log_error_source_worker():
    entry = {"plugin": "worker-3/duel", "exc_type": "X", "message": "m"}
    assert _log_error_entry_matches_source(entry, "worker-3")
    assert not _log_error_entry_matches_source(entry, "worker-4")
    assert _log_error_entry_matches_source(entry, "all")


def test_log_error_source_hub():
    entry = {"plugin": "pallas_webui", "exc_type": "X", "message": "m"}
    assert _log_error_entry_matches_source(entry, "hub")
    assert not _log_error_entry_matches_source(entry, "worker-0")
