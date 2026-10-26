import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECKOUT = Path("/tmp/opencode/maibot-nonebot-adapter-20261026")


@pytest.mark.parametrize(("suffix", "version"), [("068", "0.6.8"), ("075", "0.7.5")])
def test_unmodified_adapter_replay_records_supported_paths_and_gaps(suffix, version, tmp_path):
    python = Path(f"/tmp/opencode/maibot-adapter-probe-{suffix}/bin/python")
    if not python.is_file() or not CHECKOUT.is_dir():
        pytest.skip("isolated maim-message environment and explicit upstream checkout required")
    result = subprocess.run(
        [str(python), str(ROOT / "tools/experiments/maibot_spike/nonebot_adapter_probe.py"), str(CHECKOUT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.split("ADAPTER_REPLAY_RESULT=", 1)[1])
    assert report["maim_message"] == version
    assert report["text_conversion"]
    assert report["whitelist_blocks_other_group"]
    assert report["command_forwarded"]
    assert not report["inbound_carries_account_id"]
    assert report["requested_bot_ids"] == [None]
    assert report["target_bot"] == "200"
    assert report["actual_bot"] == "100"
    assert report["echo_calls"] == 0
    assert not report["network_tested"]
    assert not report["plugin_lifecycle_tested"]
