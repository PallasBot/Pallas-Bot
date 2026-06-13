from src.features.cmd_perm.schema import build_command_perm_ui


def test_command_perm_ui_labels_without_plugins():
    ui = build_command_perm_ui({})
    for pg in ui["plugins"]:
        assert pg["title"] == pg["title"].strip()
        assert pg["title"] != pg["plugin"] or pg["plugin"] in ("maa",)
        for cmd in pg["commands"]:
            assert cmd["label"] != cmd["command_id"], f"missing label: {cmd['command_id']}"
            assert "…" not in cmd["label"]
    draw = next(pg for pg in ui["plugins"] if pg["plugin"] == "draw")
    labels = {c["command_id"]: c["label"] for c in draw["commands"]}
    assert labels["draw.gateway"] == "牛牛网关"
    assert labels["draw.draw"] == "牛牛画画"


def test_command_perm_ui_level_labels_chinese():
    ui = build_command_perm_ui({})
    assert [lv["label"] for lv in ui["levels"]] == [
        "所有人",
        "号主",
        "群管/群主",
        "群管或号主",
        "仅超管",
    ]
