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


def test_extract_url_from_cq_segment_decodes_html_entities() -> None:
    from pallas.product.llm.vision_content import extract_url_from_cq_segment

    url = extract_url_from_cq_segment(
        "[CQ:image,file=photo.png,url=https://multimedia.nt.qq.com.cn/download?appid=100&amp;fileid=abc&amp;rkey=xyz]"
    )

    assert url == "https://multimedia.nt.qq.com.cn/download?appid=100&fileid=abc&rkey=xyz"


def test_placeholder_with_image_urls_keeps_url() -> None:
    from pallas.product.llm.vision_content import placeholder_with_image_urls

    out = placeholder_with_image_urls("[CQ:image,file=1.jpg,url=https://example.com/a.png] 这是什么")
    assert out == "[图片]:url=https://example.com/a.png 这是什么"


def test_placeholder_with_image_urls_no_url_falls_back_plain() -> None:
    from pallas.product.llm.vision_content import placeholder_with_image_urls

    assert placeholder_with_image_urls("[CQ:image,file=1.jpg]") == "[图片]"


def test_placeholder_with_image_urls_plain_text_unchanged() -> None:
    from pallas.product.llm.vision_content import placeholder_with_image_urls

    assert placeholder_with_image_urls("纯文本") == "纯文本"


def test_image_urls_from_placeholder() -> None:
    from pallas.product.llm.vision_content import image_urls_from_placeholder

    text = "[图片]:url=https://example.com/a.png 看这个 [图片]:url=https://example.com/b.png"
    assert image_urls_from_placeholder(text) == [
        "https://example.com/a.png",
        "https://example.com/b.png",
    ]


def test_image_urls_from_placeholder_plain_text_empty() -> None:
    from pallas.product.llm.vision_content import image_urls_from_placeholder

    assert image_urls_from_placeholder("没有图片占位符") == []
    assert image_urls_from_placeholder("") == []
