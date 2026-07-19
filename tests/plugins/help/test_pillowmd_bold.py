from pillowmd import CustomMarkdownRenderer

from packages.help import pillowmd_bold as bold_mod


def test_apply_help_light_bold_patch_once() -> None:
    bold_mod._PATCHED = False
    bold_mod.apply_help_light_bold_patch(0.5)
    assert CustomMarkdownRenderer.ImageDrawPro.text is not CustomMarkdownRenderer.ImageDraw.ImageDraw.text
    fn = CustomMarkdownRenderer.ImageDrawPro.text
    bold_mod.apply_help_light_bold_patch(0.5)
    assert CustomMarkdownRenderer.ImageDrawPro.text is fn
