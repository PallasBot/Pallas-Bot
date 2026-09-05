from __future__ import annotations

import asyncio
import hashlib

from tools.experimental import affinity_ab as tool


def test_result_row_includes_reply_diff_hash() -> None:
    row = tool.result_row("base", "case-1", "hi", "hello world")

    assert row["variant"] == "base"
    assert row["case"] == "case-1"
    assert row["user"] == "hi"
    assert row["reply"] == "hello world"
    assert row["hash"] == hashlib.sha1(b"hello world").hexdigest()[:8]


def test_resolve_completion_passes_temperature_to_options(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_complete(_messages, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"content": "ok"}

    monkeypatch.setattr(
        "pallas.product.llm.provider_client.complete_chat_message",
        fake_complete,
    )
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.find_provider",
        lambda _pid, **_: {
            "id": "test",
            "base_url": "http://example.invalid",
            "api_key_env": "api-key-env",
        },
    )
    monkeypatch.setattr(
        "pallas.product.llm.providers_store.resolve_provider_api_keys",
        lambda _raw: ["sk-test"],
    )

    async def run() -> None:
        complete = tool.resolve_completion("test", "model", temperature=0.3)
        await complete([{"role": "user", "content": "hi"}])

    asyncio.run(run())

    options = captured["options"]
    assert isinstance(options, dict)
    assert options["temperature"] == 0.3
    assert options["max_tokens"] == 240
