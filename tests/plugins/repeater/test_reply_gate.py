from __future__ import annotations

from packages.repeater.reply_gate import should_prepare_repeater_reply


def test_should_prepare_repeater_reply_skips_plugin_commands(monkeypatch):
    monkeypatch.setattr(
        "packages.repeater.reply_gate.is_plugin_command_plaintext",
        lambda _text: True,
    )
    plain_text = "牛牛帮助"

    assert should_prepare_repeater_reply(plain_text) is False


def test_should_prepare_repeater_reply_skips_single_char_plaintext():
    plain_text = "草"

    assert should_prepare_repeater_reply(plain_text) is False


def test_should_prepare_repeater_reply_keeps_single_char_plaintext_in_sharded_mode():
    plain_text = "草"

    assert should_prepare_repeater_reply(plain_text, sharding_active=True) is True


def test_should_prepare_repeater_reply_keeps_normal_plaintext():
    plain_text = "你好呀"

    assert should_prepare_repeater_reply(plain_text) is True
