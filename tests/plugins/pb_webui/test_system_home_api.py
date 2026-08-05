from __future__ import annotations

from types import SimpleNamespace

from packages.pb_webui import system_home_api as mod


class _CpuPercentPsutil:
    def __init__(self) -> None:
        self.calls: list[tuple[float | None, bool]] = []

    def cpu_percent(self, interval: float | None, *, percpu: bool) -> list[float]:
        self.calls.append((interval, percpu))
        return [12.5, 37.5]


def test_runtime_metrics_reads_non_blocking_cpu_sample_without_repriming(monkeypatch) -> None:
    psutil = _CpuPercentPsutil()
    monkeypatch.setitem(__import__("sys").modules, "psutil", psutil)
    monkeypatch.setattr(mod, "_gpu_metrics", lambda: {"available": False, "devices": []})

    metrics = mod._runtime_metrics()

    assert psutil.calls == [(None, True)]
    assert metrics["cpu_per_core"] == [12.5, 37.5]
    assert metrics["cpu_percent"] == 25.0


def test_cpu_model_reads_linux_model_name(monkeypatch) -> None:
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        mod.Path,
        "read_text",
        lambda *_args, **_kwargs: "processor\t: 0\nmodel\t\t: 33\nmodel name\t: AMD Ryzen Test CPU\n",
    )

    assert mod.cpu_model() == "AMD Ryzen Test CPU"


def test_cpu_model_falls_back_when_platform_reader_fails(monkeypatch) -> None:
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(mod.Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(mod.platform, "processor", lambda: "Generic CPU")

    assert mod.cpu_model() == "Generic CPU"


def test_cpu_model_reads_macos_brand_string(monkeypatch) -> None:
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        mod,
        "subprocess",
        SimpleNamespace(check_output=lambda *_args, **_kwargs: "Apple M4\n"),
        raising=False,
    )

    assert mod.cpu_model() == "Apple M4"


def test_cpu_model_reads_windows_registry(monkeypatch) -> None:
    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    winreg = SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda *_args: Key(),
        QueryValueEx=lambda *_args: ("AMD Ryzen Test CPU", 1),
    )
    monkeypatch.setattr(mod.platform, "system", lambda: "Windows")
    monkeypatch.setitem(__import__("sys").modules, "winreg", winreg)

    assert mod.cpu_model() == "AMD Ryzen Test CPU"
