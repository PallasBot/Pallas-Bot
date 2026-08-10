from pathlib import Path

from packages.help import help_theme


def test_help_font_uses_pillowmd_font_without_bundled_source_han(monkeypatch, tmp_path: Path) -> None:
    font_path = tmp_path / "smSans.ttf"
    font_path.write_bytes(b"font")
    monkeypatch.setattr(help_theme, "PILLOWMD_DEFAULT_FONT", font_path)
    monkeypatch.delenv("PALLAS_HELP_V3_FONT", raising=False)

    assert not hasattr(help_theme, "BUNDLED_SOURCE_HAN_SERIF")
    assert help_theme.resolve_help_font_path() == font_path
