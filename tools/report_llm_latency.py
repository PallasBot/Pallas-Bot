from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from math import ceil, isfinite
from pathlib import Path


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, float) or not isfinite(value) or value < 0:
        return None
    return int(value)


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    return sorted(values)[max(0, ceil(len(values) * percentile) - 1)]


def _metric(values: list[int], *, basis: str, unknown_count: int | None = None) -> dict[str, object]:
    return {
        "unit": "ms",
        "basis": basis,
        "sample_count": len(values),
        **({"unknown_count": unknown_count} if unknown_count is not None else {}),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
    }


def _event_metric(events: list[dict], field: str, *, basis: str) -> dict[str, object]:
    values = [value for row in events if (value := _number(row.get(field))) is not None]
    return _metric(values, basis=basis, unknown_count=len(events) - len(values))


def summarize_latency_events(
    events: list[dict],
    *,
    day_key: str,
    source_file_count: int,
) -> dict[str, object]:
    rows = [row for row in events if isinstance(row, dict)]
    submits = [row for row in rows if row.get("stage") == "submit"]
    providers = [row for row in rows if row.get("stage") == "provider"]
    deliveries = [row for row in rows if row.get("stage") == "delivery"]
    context = [value for row in submits if (value := _number(row.get("context_assembly_ms"))) is not None]
    provider = [value for row in providers if (value := _number(row.get("latency_ms"))) is not None]
    first_reply = [value for row in deliveries if (value := _number(row.get("first_reply_latency_ms"))) is not None]
    delivery = [value for row in deliveries if (value := _number(row.get("delivery_latency_ms"))) is not None]
    valid_statuses = {"sent", "partial", "failed", "silent"}
    statuses: Counter[str] = Counter()
    status_events: dict[str, list[dict]] = {}
    for row in deliveries:
        status = str(row.get("delivery_status") or row.get("decision") or "unknown")
        status = status if status in valid_statuses else "unknown"
        statuses[status] += 1
        status_events.setdefault(status, []).append(row)
    return {
        "window": {"local_day": day_key, "source_files": int(source_file_count)},
        "metrics": {
            "context_assembly_ms": _metric(
                context,
                basis="one observed direct-context assembly per submit event",
                unknown_count=len(submits) - len(context),
            ),
            "provider_request_ms": _metric(
                provider,
                basis="each provider attempt; retries count separately",
            ),
            "send_queue_wait_ms": {
                "unit": "ms",
                "status": "unknown",
                "basis": "not instrumented per LLM send",
                "sample_count": 0,
                "p50_ms": None,
                "p95_ms": None,
            },
            "first_effective_reply_ms": _metric(
                first_reply,
                basis="task registration to first successfully sent text bubble; progress bubbles excluded",
                unknown_count=len(deliveries) - len(first_reply),
            ),
            "delivery_ms": _metric(
                delivery,
                basis="delivery entry through the final text-bubble send attempt",
                unknown_count=len(deliveries) - len(delivery),
            ),
        },
        "delivery_status": dict(statuses),
        "delivery_metrics_by_status": {
            status: {
                "delivery_count": len(rows),
                "first_effective_reply_ms": _event_metric(
                    rows,
                    "first_reply_latency_ms",
                    basis="task registration to first successfully sent text bubble; progress bubbles excluded",
                ),
                "delivery_ms": _event_metric(
                    rows,
                    "delivery_latency_ms",
                    basis="delivery entry through the final text-bubble send attempt",
                ),
            }
            for status, rows in sorted(status_events.items())
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only LLM latency summary from turn telemetry JSONL")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/pb_webui/llm_telemetry",
    )
    parser.add_argument("--day", default=date.today().isoformat(), help="Local event day (YYYY-MM-DD)")
    args = parser.parse_args()
    day_key = date.fromisoformat(args.day).isoformat()
    paths = sorted(args.root.glob(f"turn_events-{day_key}-*.jsonl"))
    events = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(event, dict):
                events.append(event)
    print(
        json.dumps(
            summarize_latency_events(events, day_key=day_key, source_file_count=len(paths)),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
