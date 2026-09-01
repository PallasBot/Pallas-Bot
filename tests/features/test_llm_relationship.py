from __future__ import annotations

from pallas.product.llm.memory.relationship import (
    clamp_user_relationship_delta,
    extract_at_target,
    merge_relationship_facts,
    normalize_relationship_note,
    parse_relationship_teach,
    prefer_relationship_source,
    relationship_auto_fact_is_admissible,
    relationship_note_has_value,
    relationship_teach_likely,
    resolve_relationship_teach_target_id,
)
from pallas.product.llm.memory.relationship_auto import (
    extract_relationship_attitude_delta,
    extract_relationship_auto,
    parse_relationship_observe,
)
from pallas.product.llm.memory.relationship_store import decayed_weight
from pallas.product.persona.affect_kernel import build_persona_affect_contract
from pallas.product.persona.model import ResolvedPersona


def test_parse_relationship_teach_prefix() -> None:
    assert parse_relationship_teach("记住关系：阿米娅是罗德岛领袖") == "阿米娅是罗德岛领袖"
    assert parse_relationship_teach("对凯尔希，是医疗组负责人") == "对凯尔希，是医疗组负责人"


def test_parse_relationship_teach_pattern() -> None:
    assert parse_relationship_teach("银灰是我推的角色") == "银灰是我推的角色"


def test_parse_relationship_teach_rejects_emotion() -> None:
    assert parse_relationship_teach("今天烦死了") is None
    assert parse_relationship_teach("随便说点什么") is None
    assert parse_relationship_teach("对我心情不好") is None


def test_parse_relationship_teach_rejects_conversational_dui() -> None:
    assert parse_relationship_teach("对你开枪怎么了") is None
    assert parse_relationship_teach("对他别那么凶") is None
    assert parse_relationship_teach("对啊我是谁") is None


def test_relationship_teach_likely_skips_casual_chat() -> None:
    assert relationship_teach_likely("你好") is False
    assert relationship_teach_likely("对你开枪怎么了") is True
    assert relationship_teach_likely("记住关系：阿米娅是领袖") is True


def test_resolve_relationship_teach_target_id_ignores_at_bot() -> None:
    assert (
        resolve_relationship_teach_target_id(
            "[CQ:at,qq=111] 记住关系：群主",
            speaker_id=222,
            bot_self_id=111,
        )
        == 222
    )
    assert (
        resolve_relationship_teach_target_id(
            "[CQ:at,qq=333] 记住关系：发小",
            speaker_id=222,
            bot_self_id=111,
        )
        == 333
    )


def test_relationship_note_has_value() -> None:
    assert relationship_note_has_value("是这个群的群主") is True
    assert relationship_note_has_value("嗯") is False
    assert relationship_note_has_value("好烦啊") is False


def test_relationship_auto_fact_admissible_direct_statements() -> None:
    assert relationship_auto_fact_is_admissible("该用户名叫小明") is True
    assert relationship_auto_fact_is_admissible("是本群群主") is True
    assert relationship_auto_fact_is_admissible("希望被叫作队长") is True
    assert relationship_auto_fact_is_admissible("该用户喜欢发猫图") is True


def test_relationship_auto_fact_rejects_inference_and_traits() -> None:
    assert relationship_auto_fact_is_admissible("该用户习惯用塔罗牌话题与博士互动") is False
    assert relationship_auto_fact_is_admissible("该用户乐于参与群内社交，习惯主动问候新成员") is False
    assert relationship_auto_fact_is_admissible("可能依赖牛牛回复") is False
    assert relationship_auto_fact_is_admissible("自我中心") is False
    assert relationship_auto_fact_is_admissible("缺乏边界感") is False
    assert relationship_auto_fact_is_admissible("倾向于寻求陪伴") is False
    assert relationship_auto_fact_is_admissible("该用户似乎在闹脾气") is False
    assert relationship_auto_fact_is_admissible("就是随口问问") is False


def test_relationship_auto_fact_rejects_empty_and_short() -> None:
    assert relationship_auto_fact_is_admissible("") is False
    assert relationship_auto_fact_is_admissible("   ") is False
    assert relationship_auto_fact_is_admissible("嗯") is False
    assert relationship_auto_fact_is_admissible("好烦啊") is False


def test_extract_at_target() -> None:
    assert extract_at_target("[CQ:at,qq=12345] 记住关系：群主") == 12345
    assert extract_at_target("没有 at") is None


def test_normalize_relationship_note_truncates() -> None:
    note = normalize_relationship_note("x" * 500, max_len=50)
    assert 0 < len(note) <= 50


def test_decayed_weight_half_life() -> None:
    # 经过一个半衰期后权重约减半
    now = 1_000_000_000
    updated = now - 30 * 86400
    decayed = decayed_weight(1.0, updated, half_life_days=30.0, now=now)
    assert 0.45 < decayed < 0.55


def test_decayed_weight_no_decay_when_disabled() -> None:
    assert decayed_weight(0.8, 0, half_life_days=0.0, now=999) == 0.8


def test_merge_relationship_facts_dedupes_and_joins() -> None:
    merged = merge_relationship_facts("是本群群主", "是本群群主；希望被叫作队长", max_len=200)
    assert "是本群群主" in merged
    assert "希望被叫作队长" in merged
    assert merged.count("是本群群主") == 1


def test_merge_relationship_facts_replaces_call_as_slot() -> None:
    merged = merge_relationship_facts("希望被叫作队长；是本群群主", "希望被叫作小明", max_len=200)
    assert "希望被叫作小明" in merged
    assert "希望被叫作队长" not in merged
    assert "是本群群主" in merged


def test_parse_relationship_fact_view_and_guidance() -> None:
    from pallas.product.llm.memory.relationship_profile import (
        build_relationship_guidance_lines,
        parse_relationship_fact_view,
    )

    view = parse_relationship_fact_view("是本群群主；希望被叫作队长；不喜欢被叫作笨蛋；偏好直接沟通")
    assert view.preferred_name == "队长"
    assert "笨蛋" in view.avoid_names
    assert view.role_label == "群主"
    assert view.prefer_direct is True
    hints = " ".join(build_relationship_guidance_lines(view))
    assert "队长" in hints
    assert "笨蛋" in hints
    assert "直接" in hints


def test_clamp_user_relationship_delta() -> None:
    assert clamp_user_relationship_delta(0.2) == 0.15
    assert clamp_user_relationship_delta(-0.2) == -0.15
    assert clamp_user_relationship_delta(0.05) == 0.05


def test_prefer_relationship_source_keeps_teach() -> None:
    assert prefer_relationship_source("teach", "auto") == "teach"
    assert prefer_relationship_source("auto", "observe") == "observe"
    assert prefer_relationship_source("observe", "teach") == "teach"


def test_parse_relationship_observe_self_role() -> None:
    assert parse_relationship_observe("我是本群群主") == "是本群群主"
    assert parse_relationship_observe("群主是我") == "是本群群主"
    assert parse_relationship_observe("我当群管") == "是本群群管"
    assert parse_relationship_observe("叫我队长") == "希望被叫作队长"
    assert parse_relationship_observe("别叫我笨蛋") == "不喜欢被叫作笨蛋"
    assert parse_relationship_observe("记住关系：群主") is None
    assert parse_relationship_observe("你好") is None


def test_parse_relationship_observe_address_and_pref() -> None:
    assert parse_relationship_observe("你可以叫我队长啊") == "希望被叫作队长"
    assert parse_relationship_observe("我叫小明") == "希望被叫作小明"
    assert parse_relationship_observe("我在群里叫队长") == "希望被叫作队长"
    assert parse_relationship_observe("我群名片是小明") == "希望被叫作小明"
    assert parse_relationship_observe("不要叫我笨蛋") == "不喜欢被叫作笨蛋"
    assert parse_relationship_observe("别用外号叫我") == "不喜欢被叫外号"
    assert parse_relationship_observe("以后别用外号") == "不喜欢被叫外号"
    assert parse_relationship_observe("对我直说就行") == "偏好直接沟通"
    assert parse_relationship_observe("别客套吧") == "偏好直接沟通"


def test_parse_relationship_observe_rejects_noise() -> None:
    assert parse_relationship_observe("我是不是群主") is None
    assert parse_relationship_observe("叫我干什么") is None
    assert parse_relationship_observe("我叫你一声好汉") is None
    assert parse_relationship_observe("今天天气不错我们聊点别的吧哈哈哈") is None


def test_extract_relationship_attitude_delta() -> None:
    warmth, assertiveness = extract_relationship_attitude_delta("喜欢你啊")
    assert warmth > 0
    warmth_neg, _ = extract_relationship_attitude_delta("滚")
    assert warmth_neg < 0


def test_extract_relationship_auto_combines() -> None:
    update = extract_relationship_auto("我是群主")
    assert update is not None
    assert update.fact == "是本群群主"


def test_build_persona_affect_contract_applies_user_delta() -> None:
    cold = build_persona_affect_contract(ResolvedPersona(warmth=0.0), user_warmth_delta=-0.12)
    warm = build_persona_affect_contract(ResolvedPersona(warmth=0.0), user_warmth_delta=0.12)
    cold_text = " ".join(cold.stance_hints)
    warm_text = " ".join(warm.stance_hints)
    assert "距离感" in cold_text
    assert "稍熟" in warm_text
