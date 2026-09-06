from __future__ import annotations

import io
import os
import sys
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from packages.help.menu_rows import HelpMenuRow
from packages.help.plugin_detail_data import FunctionDetailData, HelpFunctionRow, PluginDetailData


def test_help_renderer_mode_defaults_to_pillow_and_accepts_html(monkeypatch) -> None:
    from packages.help import renderer

    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda key: os.environ.get(key),
    )
    monkeypatch.delenv("PALLAS_HELP_RENDERER", raising=False)
    assert renderer.help_renderer_mode() == "pillow"

    monkeypatch.setenv("PALLAS_HELP_RENDERER", "html")
    assert renderer.help_renderer_mode() == "html"


def test_help_renderer_mode_reads_repo_settings(monkeypatch) -> None:
    from packages.help import renderer

    monkeypatch.delenv("PALLAS_HELP_RENDERER", raising=False)
    monkeypatch.setattr(
        "pallas.core.foundation.config.repo_settings.repo_env_raw_value",
        lambda key: "html" if key == "PALLAS_HELP_RENDERER" else None,
    )

    assert renderer.help_renderer_mode() == "html"


def test_html_theme_is_separate_from_pillow_theme(monkeypatch) -> None:
    from packages.help import help_theme, html_theme

    light = html_theme.get_html_theme("light")
    dark = html_theme.get_html_theme("dark")

    assert light == dark
    assert light["canvas"] == "#9A9E9B"
    assert light["paper"] == "#ACAFAC"
    assert light["card"] == "#DEDED8"
    assert light["header"] == "#343A3D"
    assert light["header_panel"] == "#42494C"
    assert light["cyan"] == "#2DB9DD"
    assert light["amber"] == "#C7CD00"
    assert help_theme.ACCENT == (124, 58, 237)


def test_html_template_uses_dossier_layout_contract() -> None:
    module = _load_html_renderer()
    assert module is not None

    template = module.HTML_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'class="document-shell"' in template
    assert 'class="dossier-header"' in template
    assert 'class="instruction-strip"' in template
    assert 'class="command-navigation"' in template
    assert 'class="plugin-card-bar"' in template
    assert 'class="function-card-bar"' in template
    assert 'class="doc-section-heading"' in template
    assert '<div class="eyebrow">{{ eyebrow }}</div>' in template
    assert "PLUGIN INDEX" in template
    assert "DOSSIER" in template
    assert "COMMAND INDEX" in template
    assert "background: var(--record-header)" in template
    assert "background: var(--record-body)" in template
    assert "background: var(--content-background)" in template
    assert ".function-card { min-height: 0; }" in template
    assert ".doc-body { max-width: none;" in template
    assert "white-space: nowrap; overflow-wrap: anywhere" in template
    assert ".doc-body pre" in template
    assert ".doc-body blockquote" in template
    assert "margin-top: auto" in template
    assert "repeat({{ items|length }}, minmax(0, 1fr))" in template
    assert "repeat({{ metadata|length }}, minmax(0, 1fr))" in template
    assert "https://" not in template


def _load_html_renderer():
    try:
        return import_module("packages.help.html_renderer")
    except ModuleNotFoundError:
        return None


def test_build_menu_context_preserves_groups_and_status(monkeypatch) -> None:
    module = _load_html_renderer()
    assert module is not None

    plugin = SimpleNamespace(name="demo", module=SimpleNamespace(__file__=__file__), metadata=None)
    monkeypatch.setattr(module, "load_help_plugin_icon", lambda *_args, **_kwargs: Image.new("RGBA", (56, 56)))
    rows = [
        HelpMenuRow(
            index=1,
            plugin=plugin,
            display_name="示例插件",
            description="查看示例功能",
            enabled=True,
            help_tag="core",
        ),
        HelpMenuRow(
            index=2,
            plugin=plugin,
            display_name="关闭插件",
            description="当前不可用",
            enabled=False,
            help_tag="fun",
        ),
    ]

    context = module.build_menu_context(
        rows,
        show_ignored=False,
        total_plugin_count=2,
        total_enabled_count=1,
    )

    assert context["kind"] == "menu"
    assert context["stats"] == "共 2 个 · 启用 1"
    assert context["stats_label"] == "启用状态"
    assert context["stats_value"] == "1 / 2"
    assert [group["label"] for group in context["groups"]] == ["内核", "娱乐"]
    assert [group["number"] for group in context["groups"]] == ["01", "02"]
    assert context["groups"][0]["rows"][0]["enabled"] is True
    assert context["groups"][1]["rows"][0]["status"] == "OFF 已停用"
    assert context["groups"][0]["rows"][0]["icon"].startswith("data:image/png;base64,")
    assert context["eyebrow"] == "PALLAS / HELP / INDEX"


def test_build_plugin_context_contains_functions_and_sections(monkeypatch) -> None:
    module = _load_html_renderer()
    assert module is not None

    plugin = SimpleNamespace(name="demo", module=SimpleNamespace(__file__=__file__), metadata=None)
    monkeypatch.setattr(module, "load_help_plugin_icon", lambda *_args, **_kwargs: Image.new("RGBA", (88, 88)))
    data = PluginDetailData(
        plugin=plugin,
        display_name="示例插件",
        description="**示例**说明",
        usage="牛牛示例",
        enabled=True,
        functions=[
            HelpFunctionRow(1, "查看示例", "牛牛示例", "群内", "所有人", "—", "查看", "详情"),
        ],
    )

    context = module.build_plugin_context(data)

    assert context["kind"] == "plugin"
    assert context["status"] == "已启用"
    assert context["status_code"] == "ON"
    assert context["function_count"] == 1
    assert context["function_count_label"] == "FUNCTIONS"
    assert context["functions"][0]["func"] == "查看示例"
    assert context["functions"][0]["meta"] == "群内 · 所有人"
    assert context["functions"][0]["index_label"] == "01"
    assert context["description"] == "示例说明"
    assert context["function_section_number"] == "01"
    assert context["sections"] == []
    assert context["eyebrow"] == "PALLAS / PLUGIN / DOSSIER"


def test_build_plugin_context_keeps_long_description_and_numbers_sections(monkeypatch) -> None:
    module = _load_html_renderer()
    assert module is not None

    plugin = SimpleNamespace(name="demo", module=SimpleNamespace(__file__=__file__), metadata=None)
    monkeypatch.setattr(module, "load_help_plugin_icon", lambda *_args, **_kwargs: Image.new("RGBA", (88, 88)))
    description = "这是一段需要在正文完整保留的较长插件说明。" * 12
    data = PluginDetailData(
        plugin=plugin,
        display_name="示例插件",
        description=description,
        usage="用法",
        enabled=True,
        functions=[HelpFunctionRow(1, "查看示例", "牛牛示例", "群内", "所有人", "—", "查看", "详情")],
        extra_sections=[("补充说明", "额外内容")],
    )

    context = module.build_plugin_context(data)

    assert context["description"] != description
    assert context["description"].endswith("…")
    assert context["function_section_number"] == "01"
    assert [(section["number"], section["title"], section["body"]) for section in context["sections"]] == [
        ("02", "说明", description),
        ("03", "补充说明", "额外内容"),
    ]


def test_build_plugin_context_numbers_usage_when_no_functions(monkeypatch) -> None:
    module = _load_html_renderer()
    assert module is not None

    plugin = SimpleNamespace(name="demo", module=SimpleNamespace(__file__=__file__), metadata=None)
    monkeypatch.setattr(module, "load_help_plugin_icon", lambda *_args, **_kwargs: Image.new("RGBA", (88, 88)))
    data = PluginDetailData(
        plugin=plugin,
        display_name="示例插件",
        description="短说明",
        usage="插件用法",
        enabled=True,
    )

    context = module.build_plugin_context(data)

    assert [(section["number"], section["title"]) for section in context["sections"]] == [("01", "插件内用法")]


def test_build_plugin_context_flattens_short_multiline_description_without_ellipsis(monkeypatch) -> None:
    module = _load_html_renderer()
    assert module is not None

    plugin = SimpleNamespace(name="demo", module=SimpleNamespace(__file__=__file__), metadata=None)
    monkeypatch.setattr(module, "load_help_plugin_icon", lambda *_args, **_kwargs: Image.new("RGBA", (88, 88)))
    description = "第一行说明\n第二行说明"
    data = PluginDetailData(
        plugin=plugin,
        display_name="示例插件",
        description=description,
        usage="用法",
        enabled=True,
        functions=[HelpFunctionRow(1, "查看示例", "牛牛示例", "群内", "所有人", "—", "查看", "详情")],
    )

    context = module.build_plugin_context(data)

    assert context["description"] == "第一行说明 第二行说明"
    assert [(section["number"], section["body"]) for section in context["sections"]] == [("02", description)]


def test_build_function_context_removes_markdown_code_fences_from_display_command() -> None:
    module = _load_html_renderer()
    assert module is not None

    data = FunctionDetailData(
        plugin=SimpleNamespace(name="demo"),
        display_name="示例插件",
        func_name="查看示例",
        index=1,
        total=1,
        say="查看示例 | `demo query <target>`",
        scene="群内",
        perm="所有人",
        cooldown="—",
        brief="查看示例",
        detail="发送命令即可。",
    )

    context = module.build_function_context(data)

    assert context["say"] == "查看示例 | demo query <target>"


def test_build_function_context_contains_navigation_and_command() -> None:
    module = _load_html_renderer()
    assert module is not None

    data = FunctionDetailData(
        plugin=SimpleNamespace(name="demo"),
        display_name="示例插件",
        func_name="查看示例",
        index=2,
        total=3,
        say="牛牛示例",
        scene="群内",
        perm="所有人",
        cooldown="冷却 3 秒",
        brief="查看示例",
        detail="发送命令即可。",
    )

    context = module.build_function_context(data)

    assert context["kind"] == "function"
    assert context["chips"] == ["群内", "所有人", "冷却 3 秒"]
    assert context["say"] == "牛牛示例"
    assert context["metadata"] == [
        {"label": "SCENE", "title": "触发场景", "value": "群内"},
        {"label": "ACCESS", "title": "何人可用", "value": "所有人"},
        {"label": "COOLDOWN", "title": "冷却时间", "value": "冷却 3 秒"},
    ]
    assert context["eyebrow"] == "PALLAS / COMMAND / BRIEF"
    assert context["breadcrumb"] == "帮助总览 / 示例插件 / 查看示例"
    assert context["footer_items"] == [
        {"label": "插件", "command": "牛牛帮助 示例插件"},
        {"label": "上一项", "command": "牛牛帮助 示例插件 1"},
        {"label": "下一项", "command": "牛牛帮助 示例插件 3"},
        {"label": "总览", "command": "牛牛帮助"},
    ]
    assert context["footer"] == (
        "插件：牛牛帮助 示例插件 · 上一项：牛牛帮助 示例插件 1 · 下一项：牛牛帮助 示例插件 3 · 总览：牛牛帮助"
    )


def test_build_function_context_omits_missing_metadata_and_invalid_navigation() -> None:
    module = _load_html_renderer()
    assert module is not None

    data = FunctionDetailData(
        plugin=SimpleNamespace(name="demo"),
        display_name="示例插件",
        func_name="第一项",
        index=1,
        total=1,
        say="牛牛示例",
        scene="群内",
        perm="—",
        cooldown="",
        brief="第一项",
        detail="",
    )

    context = module.build_function_context(data)

    assert context["metadata"] == [{"label": "SCENE", "title": "触发场景", "value": "群内"}]
    assert context["footer_items"] == [
        {"label": "插件", "command": "牛牛帮助 示例插件"},
        {"label": "总览", "command": "牛牛帮助"},
    ]


def test_build_function_context_formats_lists_and_escapes_markup() -> None:
    module = _load_html_renderer()
    assert module is not None

    data = FunctionDetailData(
        plugin=SimpleNamespace(name="demo"),
        display_name="示例插件",
        func_name="查看示例",
        index=1,
        total=1,
        say="牛牛示例",
        scene="群内",
        perm="所有人",
        cooldown="—",
        brief="查看示例",
        detail="- 第一项\n- 第二项\n\n说明 <script>alert(1)</script>",
    )

    context = module.build_function_context(data)
    body_html = context["sections"][0]["body_html"]

    assert "<ul>" in body_html
    assert "<li>第一项</li>" in body_html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body_html
    assert "<script>" not in body_html


def test_body_html_renders_fenced_commands_as_safe_code_blocks() -> None:
    module = _load_html_renderer()
    assert module is not None

    body_html = module._body_html("说明\n\n```bash\nskland bind <token|cred>\n```\n")

    assert "<pre><code>skland bind &lt;token|cred&gt;</code></pre>" in body_html
    assert "```" not in body_html
    assert "bash" not in body_html


def test_body_html_renders_blockquotes_as_separate_blocks() -> None:
    module = _load_html_renderer()
    assert module is not None

    body_html = module._body_html("> 注意：需要回复一条图片\n> 再继续操作")

    assert "<blockquote>注意：需要回复一条图片<br>再继续操作</blockquote>" in body_html


async def test_render_help_template_uses_htmlrender_template_api(monkeypatch) -> None:
    module = _load_html_renderer()
    assert module is not None

    render_template = AsyncMock(return_value=b"png")
    monkeypatch.setitem(
        sys.modules,
        "nonebot_plugin_htmlrender.render",
        SimpleNamespace(render_template=render_template),
    )

    result = await module.render_help_template({"kind": "menu"})

    assert result == b"png"
    render_template.assert_awaited_once()
    kwargs = render_template.await_args.kwargs
    assert kwargs["template_name"] == "help.html"
    assert kwargs["templates"] == {"kind": "menu"}
    assert kwargs["resolve_resources"] is False


@pytest.mark.asyncio
async def test_menu_render_uses_html_renderer_when_selected(monkeypatch) -> None:
    from packages.help import renderer

    row = SimpleNamespace(
        index=1,
        display_name="示例",
        description="示例功能",
        enabled=True,
        help_tag="core",
        plugin=SimpleNamespace(name="demo", module=SimpleNamespace(__file__=__file__), metadata=None),
    )
    html_render = AsyncMock(return_value=b"html-image")
    monkeypatch.setattr(renderer, "help_renderer_mode", lambda: "html")
    monkeypatch.setattr(renderer, "_help_image_cache_suffix", lambda: "test")
    monkeypatch.setattr(renderer, "render_help_html_image_bytes", html_render, raising=False)
    monkeypatch.setattr(
        "packages.help.draw_plugin_menu.draw_plugin_menu_image",
        lambda *_args, **_kwargs: pytest.fail("Pillow renderer should not be selected"),
    )

    result = await renderer.render_plugin_menu_to_image(
        [row],
        show_ignored=False,
        group_id=2,
        total_plugin_count=1,
        total_enabled_count=1,
    )

    assert result == b"html-image"
    html_render.assert_awaited_once()


@pytest.mark.asyncio
async def test_menu_render_falls_back_to_pillow_after_html_failure(monkeypatch) -> None:
    from packages.help import renderer

    row = SimpleNamespace(
        index=1,
        display_name="示例",
        description="示例功能",
        enabled=True,
        help_tag="core",
        plugin=SimpleNamespace(name="demo", module=SimpleNamespace(__file__=__file__), metadata=None),
    )
    pillow_render = AsyncMock(return_value=b"pillow-image")
    monkeypatch.setattr(renderer, "help_renderer_mode", lambda: "html")
    monkeypatch.setattr(renderer, "_help_image_cache_suffix", lambda: "test")
    monkeypatch.setattr(renderer, "render_help_html_image_bytes", AsyncMock(side_effect=RuntimeError("browser")))
    monkeypatch.setattr(renderer, "render_v3_image_bytes", pillow_render)
    monkeypatch.setattr(
        "packages.help.draw_plugin_menu.draw_plugin_menu_image",
        lambda *_args, **_kwargs: Image.new("RGB", (920, 200)),
    )

    result = await renderer.render_plugin_menu_to_image(
        [row],
        show_ignored=False,
        group_id=2,
        total_plugin_count=1,
        total_enabled_count=1,
    )

    assert result == b"pillow-image"
    pillow_render.assert_awaited_once()


@pytest.mark.asyncio
async def test_detail_render_uses_html_renderer_when_selected(monkeypatch) -> None:
    from packages.help import renderer

    data = PluginDetailData(
        plugin=SimpleNamespace(name="demo"),
        display_name="示例插件",
        description="说明",
        usage="用法",
        enabled=True,
    )
    html_render = AsyncMock(return_value=b"html-detail")
    monkeypatch.setattr(renderer, "help_renderer_mode", lambda: "html")
    monkeypatch.setattr(renderer, "_help_image_cache_suffix", lambda: "test")
    monkeypatch.setattr(renderer, "render_help_html_image_bytes", html_render)
    monkeypatch.setattr(
        "packages.help.draw_plugin_detail.draw_plugin_detail_image",
        lambda *_args, **_kwargs: pytest.fail("Pillow renderer should not be selected"),
    )

    result = await renderer.render_plugin_detail_to_image(data, group_id=2)

    assert result == b"html-detail"
    html_render.assert_awaited_once()


@pytest.mark.asyncio
async def test_html_renderer_normalizes_template_png_before_caching(tmp_path, monkeypatch) -> None:
    from packages.help import renderer

    image = Image.new("RGBA", (920, 160), (20, 30, 35, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    monkeypatch.setattr(renderer, "plugin_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(renderer, "_help_image_cache_suffix", lambda: "html-test")
    render_template = AsyncMock(return_value=buffer.getvalue())
    monkeypatch.setattr("packages.help.html_renderer.render_help_template", render_template)

    first = await renderer.render_help_html_image_bytes(
        "html-cache",
        {"kind": "function"},
        group_id=42,
        style_name="detail_html_v1",
    )
    second = await renderer.render_help_html_image_bytes(
        "html-cache",
        {"kind": "function"},
        group_id=42,
        style_name="detail_html_v1",
    )

    assert first == second
    render_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_plugin_detail_render_helper_is_available() -> None:
    from packages.help import renderer

    render_detail = getattr(renderer, "render_plugin_detail_to_image", None)

    assert render_detail is not None


def test_help_preview_uses_unified_plugin_renderer() -> None:
    from packages.help import preview

    render_detail = getattr(preview, "render_plugin_detail_to_image", None)

    assert render_detail is not None
