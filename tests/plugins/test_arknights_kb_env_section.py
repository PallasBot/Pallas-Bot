"""内建 PRTS 配置在控制台中有明确映射与中文标签。"""

from pallas.console.webui.env_sections import _arknights_kb_section
from pallas.console.webui.field_labels import FIELD_LABELS

PRTS_FIELDS = (
    "prts_corpus_enabled",
    "prts_corpus_packs",
    "prts_corpus_include_endfield",
    "prts_corpus_search_limit",
    "prts_corpus_read_max_lines",
    "prts_corpus_read_max_chars",
    "prts_corpus_download_timeout_sec",
    "prts_corpus_cache_max_mb",
    "prts_corpus_query_max_mb",
)


def test_prts_fields_have_env_mapping_and_labels() -> None:
    section = _arknights_kb_section()
    for field in PRTS_FIELDS:
        assert section.field_to_env.get(field) == field.upper()
        assert FIELD_LABELS.get(field)


def test_prts_fields_have_help() -> None:
    fields = _arknights_kb_section().model_cls.model_fields
    for field in PRTS_FIELDS:
        assert field in fields
        assert fields[field].description

    for field in ("prts_corpus_cache_max_mb", "prts_corpus_query_max_mb"):
        description = fields[field].description
        assert "16–256 MiB" in description
        assert "RSS" in description
        assert "重启 Bot/MCP" in description
