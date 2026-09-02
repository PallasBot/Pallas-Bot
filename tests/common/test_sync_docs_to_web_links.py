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
FILE_MAP = _MOD.FILE_MAP


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
            "[docker](/maintainer/deploy/docker)",
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
        (
            "[faq](/FAQ)",
            "[faq](/deploy/faq)",
        ),
    ],
)
def test_transform_common_webui_dead_link_patterns(src: str, expected: str) -> None:
    assert transform_for_vitepress(src) == expected


def test_maintainer_logs_page_is_synced_to_docs_repo() -> None:
    assert FILE_MAP["maintainer/operate/logs.md"] == "maintainer/operate/logs.md"


def test_guide_update_page_is_synced_to_docs_repo() -> None:
    assert FILE_MAP["guide/update.md"] == "guide/update.md"


def test_sync_copies_concepts_topology_svg(tmp_path: Path) -> None:
    _MOD.sync(tmp_path)

    assert (tmp_path / "src/public/assets/concepts-topology.svg").is_file()
