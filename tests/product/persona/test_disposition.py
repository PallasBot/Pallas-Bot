from pallas.product.persona.compile_persona_prompt import compile_persona_prompt
from pallas.product.persona.disposition import compile_disposition_prompt
from pallas.product.persona.model import ResolvedPersona


def test_compile_disposition_prompt_keeps_account_style_compact() -> None:
    prompt = compile_disposition_prompt({
        "disposition": {
            "approach": "先接住再判断",
            "initiative": "被明确叫到才主动回应",
            "conflict": "不同意时给理由",
            "do": ["短句", "短句", "直说结论"],
            "dont": ["客服腔"],
        }
    })

    assert "【账号处事风格】" in prompt
    assert prompt.count("短句") == 1
    assert "客服腔" in prompt


def test_chat_prompt_includes_disposition_but_repeater_does_not() -> None:
    persona = ResolvedPersona()
    bot_persona = {"disposition": {"approach": "先接住再判断"}}

    chat = compile_persona_prompt(
        persona,
        None,
        bot_id=1,
        base_system="基础",
        bot_persona=bot_persona,
        prompt_profile="chat",
    )
    repeater = compile_persona_prompt(
        persona,
        None,
        bot_id=1,
        base_system="基础",
        bot_persona=bot_persona,
        prompt_profile="repeater",
    )

    assert "【账号处事风格】" in chat.system
    assert "【账号处事风格】" not in repeater.system
