from __future__ import annotations

from pallas.product.llm.vision_content import user_message_has_vision_content


def test_user_message_has_vision_content_image() -> None:
    assert user_message_has_vision_content("[CQ:image,file=abc.jpg]")
    assert not user_message_has_vision_content("纯文本")
    assert not user_message_has_vision_content("")


def test_strip_vision_segments_for_history() -> None:
    from pallas.product.llm.vision_content import strip_vision_segments_for_history

    assert strip_vision_segments_for_history("[CQ:image,file=abc]") == "[图片]"
    assert strip_vision_segments_for_history("[CQ:image,file=abc] 看看这个") == "[图片] 看看这个"
    assert strip_vision_segments_for_history("纯文本") == "纯文本"


def test_extract_vision_message_payload_urls() -> None:
    from pallas.product.llm.vision_content import extract_vision_message_payload

    payload = extract_vision_message_payload("[CQ:image,file=1.jpg,url=https://example.com/a.png] 这是什么")
    assert payload.has_image is True
    assert payload.image_urls == ("https://example.com/a.png",)
    assert payload.plain_text == "这是什么"


def test_extract_url_from_cq_segment_file_http() -> None:
    from pallas.product.llm.vision_content import extract_url_from_cq_segment

    url = extract_url_from_cq_segment("[CQ:image,file=https://cdn.example.com/x.jpg]")
    assert url == "https://cdn.example.com/x.jpg"
