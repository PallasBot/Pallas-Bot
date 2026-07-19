from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap


def _assert_subprocess_import(module_name: str, attr_name: str) -> None:
    script = textwrap.dedent(
        f"""
        import importlib
        mod = importlib.import_module({module_name!r})
        attr = getattr(mod, {attr_name!r})
        assert callable(attr), {attr_name!r}
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )


def test_import_corpus_contamination_without_llm_client_cycle() -> None:
    mod = importlib.import_module("pallas.product.llm.corpus_contamination")

    assert callable(mod.reject_corpus_learn_message)


def test_import_repository_pg_without_llm_session_store_cycle() -> None:
    _assert_subprocess_import("pallas.core.foundation.db.repository_pg", "pg_pool_live_stats")


def test_import_llm_memory_package_without_cycle() -> None:
    _assert_subprocess_import("pallas.product.llm.memory", "is_llm_memory_store_available")
