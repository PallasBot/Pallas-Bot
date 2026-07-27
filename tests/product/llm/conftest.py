"""LLM 产品单测：禁止写入真实 data/ 下的用量账本与 token 日文件。"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_llm_usage_ledger(tmp_path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "llm_usage"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "pallas.product.llm.usage_ledger.usage_ledger_dir",
        lambda: root,
    )
    monkeypatch.setattr(
        "pallas.product.llm.token_metrics.stats_file_path",
        lambda: tmp_path / "llm_token_stats.json",
    )
    return root
