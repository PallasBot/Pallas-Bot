from __future__ import annotations

import pytest

from pallas.core.platform.federate import ingress_audit


@pytest.fixture(autouse=True)
def reset_audit() -> None:
    ingress_audit.reset_federate_ingress_audit_for_tests()


@pytest.mark.asyncio
async def test_audit_records_are_batched_before_redis_write(monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[dict[str, int]] = []
    monkeypatch.setattr(
        ingress_audit,
        "write_federate_ingress_audit_counts_sync",
        lambda counts: writes.append(counts),
    )

    ingress_audit.record_federate_ingress_audit(capability="llm_alias", outcome="eligible")
    ingress_audit.record_federate_ingress_audit(capability="llm_alias", outcome="winner")

    assert writes == []
    await ingress_audit.flush_federate_ingress_audit()
    assert writes == [{"llm_alias:eligible": 1, "llm_alias:winner": 1}]
