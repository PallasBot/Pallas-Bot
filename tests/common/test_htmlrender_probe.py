"""htmlrender 渲染后端探测逻辑测试。"""

from types import SimpleNamespace

import pytest

from pallas.core.platform.render import htmlrender_probe as probe


def _render_mod(available: bool | None = None, reason: str | None = None) -> SimpleNamespace:
    if available is not None:
        return SimpleNamespace(
            is_render_backend_available=lambda _b: available,
            get_render_backend_status=lambda _b: SimpleNamespace(reason=reason),
        )
    return SimpleNamespace()


def _consts_mod() -> SimpleNamespace:
    class _RB:
        PLAYWRIGHT = "playwright"

        def __init__(self, value: str):
            self.value = value

        def __eq__(self, other: object) -> bool:
            return self.value == other

        def __hash__(self) -> int:
            return hash(self.value)

    return SimpleNamespace(RenderBackend=_RB)


@pytest.fixture
def patch_imports(monkeypatch: pytest.MonkeyPatch):
    """默认给探测注入假 htmlrender 模块，避免真实导入触发插件上下文。"""
    state = {"available": None, "reason": None, "raise_import": False}

    def _fake_import(name: str, **_kwargs):
        if state["raise_import"]:
            raise ImportError(name)
        if name == probe._CONSTS_MODULE:
            return _consts_mod()
        if name == probe._RENDER_MODULE:
            return _render_mod(state["available"], state["reason"])
        raise ImportError(name)

    monkeypatch.setattr(probe, "import_module", _fake_import)
    return state


async def test_probe_skips_when_backend_unset(monkeypatch: pytest.MonkeyPatch, patch_imports) -> None:
    """RENDER_BACKEND 未设置时直接返回，不探测。"""
    monkeypatch.delenv("RENDER_BACKEND", raising=False)
    patch_imports["available"] = True
    await probe.probe_htmlrender_backend()


async def test_probe_skips_when_module_missing(monkeypatch: pytest.MonkeyPatch, patch_imports) -> None:
    """htmlrender 渲染模块不可导入时静默返回。"""
    monkeypatch.setenv("RENDER_BACKEND", "playwright")
    patch_imports["raise_import"] = True
    await probe.probe_htmlrender_backend()


async def test_probe_warns_when_backend_unavailable(monkeypatch: pytest.MonkeyPatch, patch_imports) -> None:
    """渲染后端不可用时输出含安装指引的告警。"""
    import loguru

    monkeypatch.setenv("RENDER_BACKEND", "playwright")
    patch_imports["available"] = False
    patch_imports["reason"] = "浏览器未安装"

    records: list[str] = []

    def capture_warning(message: str, *args, **kwargs) -> None:
        records.append(str(message).format(*args, **kwargs))
        return None

    monkeypatch.setattr(loguru.logger, "warning", capture_warning)

    await probe.probe_htmlrender_backend()

    assert any("playwright install chromium" in rec for rec in records)


async def test_probe_silent_when_backend_available(monkeypatch: pytest.MonkeyPatch, patch_imports) -> None:
    """渲染后端可用时不输出告警。"""
    import loguru

    monkeypatch.setenv("RENDER_BACKEND", "playwright")
    patch_imports["available"] = True

    records: list[str] = []

    def capture_warning(message: str, *args, **kwargs) -> None:
        records.append(str(message).format(*args, **kwargs))
        return None

    monkeypatch.setattr(loguru.logger, "warning", capture_warning)

    await probe.probe_htmlrender_backend()

    assert records == []
