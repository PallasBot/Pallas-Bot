"""sync_docs_to_web：常见相对链接须变成 VitePress 站内路径，避免 Docs CI 死链。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "scripts" / "sync_docs_to_web.py"
_SPEC = importlib.util.spec_from_file_location("sync_docs_to_web", _SCRIPT)
assert _SPEC is not None
assert _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
transform_for_vitepress = _MOD.transform_for_vitepress


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        (
            "[pb](../../../plugins/pb_protocol/README.md)",
            "[pb](/plugins/pb_protocol)",
        ),
        (
            "[rh](../../../plugins/request_handler/README.md)",
            "[rh](/plugins/request_handler)",
        ),
        (
            "[docker](../../../DockerDeployment.md)",
            "[docker](/deploy/docker)",
        ),
        (
            "[stats](../community_stats.md)",
            "[stats](/common/community_stats)",
        ),
        (
            "[perm](../cmd_perm/README.md)",
            "[perm](/common/cmd_perm)",
        ),
        (
            "[api](api/README.md)",
            "[api](/common/webui/api/)",
        ),
        (
            "[bad](/plugins/cmd_perm)",
            "[bad](/common/cmd_perm)",
        ),
        (
            "[peer](../repeater/README.md)",
            "[peer](/plugins/repeater)",
        ),
    ],
)
def test_transform_common_webui_dead_link_patterns(src: str, expected: str) -> None:
    assert transform_for_vitepress(src) == expected
