from packages.help.help_constants import HELP_STATUS_OFF, HELP_STATUS_ON, HELP_STATUS_PLACEHOLDER
from packages.help.plugin_manager import apply_status_marks_to_plugin_table


def test_apply_status_marks_row_order_and_description_safe() -> None:
    md = (
        "## 插件列表\n\n"
        f"| 序号 | 名称 | 状态 | 简介 |\n"
        f"|------|------|------|------|\n"
        f"| 1 | A | {HELP_STATUS_PLACEHOLDER} | 说明 {HELP_STATUS_PLACEHOLDER} 勿替换 |\n"
        f"| 2 | B | {HELP_STATUS_PLACEHOLDER} | 普通说明 |\n"
    )
    out = apply_status_marks_to_plugin_table(md, [HELP_STATUS_ON, HELP_STATUS_OFF])
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("|") and "序号" not in ln and "---" not in ln]
    assert len(lines) == 2
    assert HELP_STATUS_ON in lines[0]
    assert HELP_STATUS_OFF in lines[1]
    assert lines[0].count(HELP_STATUS_PLACEHOLDER) == 1
    assert HELP_STATUS_ON not in lines[0].split("|")[1]
