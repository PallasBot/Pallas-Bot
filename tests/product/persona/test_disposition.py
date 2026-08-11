from pallas.product.persona.compile_persona_prompt import compile_persona_prompt
from pallas.product.persona.disposition import resolve_persona_disposition
from pallas.product.persona.model import ResolvedPersona


def test_resolve_persona_disposition_keeps_account_style_compact() -> None:
    disposition = resolve_persona_disposition({
        "disposition": {
            "approach": "先接住再判断",
            "initiative": "被明确叫到才主动回应",
            "conflict": "不同意时给理由",
            "do": ["短句", "短句", "直说结论"],
            "dont": ["客服腔"],
        }
    })

    assert disposition.approach == "先接住再判断"
    assert disposition.do == ["短句", "直说结论"]
    assert disposition.dont == ["客服腔"]


def test_chat_prompt_keeps_disposition_out_of_final_system() -> None:
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
    assert "【账号处事风格】" not in chat.system
    assert "先接住再判断" not in chat.system
