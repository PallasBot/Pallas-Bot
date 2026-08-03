from __future__ import annotations

import sys


def test_quality_eval_cli_exposes_explicit_matrix_and_baseline_flags(monkeypatch) -> None:
    from tools.run_llm_quality_eval import parse_args

    monkeypatch.setattr(sys, "argv", ["run_llm_quality_eval.py", "--matrix", "anonymous", "--write-baseline"])

    args = parse_args()

    assert args.matrix == "anonymous"
    assert args.write_baseline is True
