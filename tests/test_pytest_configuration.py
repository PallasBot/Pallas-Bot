from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_collection_does_not_start_global_plugin_lifespan(tmp_path):
    pytest.importorskip("nonebug")
    conftest = Path(__file__).with_name("conftest.py")
    (tmp_path / "conftest.py").write_bytes(conftest.read_bytes())
    (tmp_path / "test_collected_plugin.py").write_text(
        "import nonebot\n"
        "from nonebug import NONEBOT_START_LIFESPAN\n"
        "@nonebot.get_driver().on_startup\n"
        "async def requires_external_services():\n"
        "    raise AssertionError('collection must not start production services')\n"
        "def test_initialized_without_implicit_startup(pytestconfig):\n"
        "    assert nonebot.get_driver() is not None\n"
        "    assert pytestconfig.stash[NONEBOT_START_LIFESPAN] is False\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "no:cacheprovider", "-o", "asyncio_mode=auto"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
