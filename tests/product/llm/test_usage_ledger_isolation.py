"""确认 product/llm 单测不会写入真实用量账本目录。"""

from __future__ import annotations

from pathlib import Path

from pallas.product.llm import usage_ledger as usage_ledger_mod
from pallas.product.llm.token_metrics import clear_llm_token_metrics_for_tests, record_llm_token_usage


def test_autouse_isolates_usage_ledger_from_repo_data(tmp_path: Path) -> None:
    clear_llm_token_metrics_for_tests()
    root = usage_ledger_mod.usage_ledger_dir()
    assert root == tmp_path / "llm_usage"
    assert "data/pb_webui/llm_usage" not in str(root).replace("\\", "/")
    record_llm_token_usage(
        task="llm_chat",
        provider="openai",
        model="gpt-4.1-mini",
        prompt_tokens=80,
        completion_tokens=20,
    )
    files = list(root.glob("*.jsonl"))
    assert files
    text = files[0].read_text(encoding="utf-8")
    assert "gpt-4.1-mini" in text
    real = Path(__file__).resolve().parents[3] / "data" / "pb_webui" / "llm_usage"
    if real.is_dir():
        for path in real.glob("*.jsonl"):
            assert "gpt-4.1-mini" not in path.read_text(encoding="utf-8")
