from pathlib import Path

import pytest

_MS_CFG = Path(__file__).resolve().parents[2] / "src" / "common" / "message_scrub" / "config.py"
skip_no_message_scrub = pytest.mark.skipif(not _MS_CFG.is_file(), reason="无 message_scrub 配置模块")


@skip_no_message_scrub
def test_list_webui_env_sections_contains_message_scrub():
    from src.common.webui_env_sections import list_webui_env_sections

    rows = list_webui_env_sections()
    ids = {r["id"] for r in rows}
    assert "message_scrub" in ids


@skip_no_message_scrub
def test_message_scrub_payload_shape():
    from src.common.webui_env_sections import webui_env_section_payload

    data = webui_env_section_payload("message_scrub")
    assert data["plugin"] == "message_scrub"
    assert data["module"]
    names = {f["name"] for f in data["fields"]}
    assert "inbound_filter_substrings" in names
    assert "scrub_review_providers_key_present" not in names
    for f in data["fields"]:
        assert f["env_key"]
        assert f["kind"] in ("bool", "int", "float", "json", "string")


@skip_no_message_scrub
def test_message_scrub_patch_roundtrip(tmp_path, monkeypatch):
    from src.common import env_dotenv as ed
    from src.common.webui_env_sections import apply_webui_env_section_patch

    env_file = tmp_path / ".env"
    monkeypatch.setattr(ed, "repo_env_path", lambda: env_file)
    apply_webui_env_section_patch("message_scrub", {"inbound_filter_substrings": "a,b"})
    text = env_file.read_text(encoding="utf-8")
    assert "PALLAS_INBOUND_FILTER_SUBSTRINGS=a,b" in text
