from pallas.core.shared.utils.array2cqcode import try_convert_to_cqcode
from pallas.core.shared.utils.array2cqcode.message_segment import BaseMessageSegment


def test_escape_coerces_int_cq_fields() -> None:
    assert BaseMessageSegment.escape(12345) == "12345"
    assert BaseMessageSegment.escape("a,b") == "a&#44;b"


def test_at_segment_with_int_qq() -> None:
    seg = BaseMessageSegment(type="at", data={"qq": 3627507529})
    assert seg.cqcode == "[CQ:at,qq=3627507529]"


def test_try_convert_list_with_int_fields() -> None:
    payload = [
        {"type": "at", "data": {"qq": 123456}},
        {"type": "text", "data": {"text": " hello"}},
    ]
    assert try_convert_to_cqcode(payload) == "[CQ:at,qq=123456] hello"
