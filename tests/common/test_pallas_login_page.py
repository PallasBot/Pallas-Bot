from __future__ import annotations

from src.common.webui.login_page import render_pallas_login_page_html


def test_render_pallas_login_page_contains_branding_and_form() -> None:
    html = render_pallas_login_page_html(
        document_title="登录 · Test",
        surface_label="控制台",
        tagline="副标题",
        form_action="/pallas/login",
        next_path="/pallas/",
        error_message="错了",
        head_extra_html="",
        footer_note="",
        favicon_variant="console",
    )
    assert "登录 · Test" in html
    assert "Pallas" in html
    assert "控制台" in html
    assert 'action="/pallas/login"' in html
    assert 'name="next"' in html
    assert 'value="/pallas/"' in html
    assert "错了" in html
    assert "__pallasLoginInitTheme" in html
    assert "data:image/svg+xml" in html
    assert "▤" not in html


def test_login_page_protocol_favicon_differs_from_console() -> None:
    console = render_pallas_login_page_html(
        document_title="T",
        surface_label="控制台",
        tagline="",
        form_action="/a",
        next_path="/a/",
        favicon_variant="console",
    )
    protocol = render_pallas_login_page_html(
        document_title="T",
        surface_label="协议端",
        tagline="",
        form_action="/b",
        next_path="/b/",
        favicon_variant="protocol",
        shell_brand_icon_base="/protocol/slug",
    )
    assert "/protocol/slug/_pallas_ui/pallas-priest.png" in protocol
    assert 'rel="icon" type="image/png"' in protocol
    assert "login-logo--img" in protocol
    assert "login-logo-img" in protocol
    assert "data:image/svg+xml" not in protocol
    assert "%232563eb" in console
    assert "◇" in console


def test_login_page_protocol_without_shell_base_uses_svg_glyph() -> None:
    html = render_pallas_login_page_html(
        document_title="T",
        surface_label="协议端",
        tagline="",
        form_action="/b",
        next_path="/b/",
        favicon_variant="protocol",
    )
    assert "%230d9488" in html
    assert "▤" in html
