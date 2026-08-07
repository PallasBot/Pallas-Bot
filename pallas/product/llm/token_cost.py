"""LLM token 费用：按提供方模型单价计算（币种与画画统计一致，由配置声明）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def normalize_cost_currency(raw: object) -> str:
    return str(raw or "").strip().upper()[:16]


def _nonneg_float(raw: object) -> float:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if value != value or value < 0:  # NaN / negative
        return 0.0
    return value


def normalize_model_price_row(raw: object) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    price_in = _nonneg_float(raw.get("price_in"))
    price_out = _nonneg_float(raw.get("price_out"))
    cache_price_in = _nonneg_float(raw.get("cache_price_in"))
    cache_price_out = _nonneg_float(raw.get("cache_price_out"))
    if price_in <= 0 and price_out <= 0 and cache_price_in <= 0 and cache_price_out <= 0:
        return None
    return {
        "price_in": price_in,
        "price_out": price_out,
        "cache_price_in": cache_price_in,
        "cache_price_out": cache_price_out,
    }


def normalize_model_pricing(raw: object) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        model = str(key or "").strip()
        if not model:
            continue
        row = normalize_model_price_row(value)
        if row is not None:
            out[model] = row
    return out


def compute_usage_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    price_in: float = 0.0,
    price_out: float = 0.0,
    cache_price_in: float = 0.0,
    cache_price_out: float = 0.0,
) -> float:
    """按百万 tokens 单价计费：非缓存输入×price_in + 缓存命中×cache_price_in + 输出×price_out。

    ``prompt_tokens`` 为非缓存输入；cache 拆分由 ``token_usage`` 完成。
    费用四舍五入到 6 位小数。
    """
    million = 1_000_000.0
    miss = max(0, int(prompt_tokens))
    hit = max(0, int(cache_read_tokens))
    cost = 0.0
    if price_in > 0 and miss > 0:
        cost += (miss / million) * price_in
    if price_out > 0 and completion_tokens > 0:
        cost += (int(completion_tokens) / million) * price_out
    if cache_price_in > 0 and hit > 0:
        cost += (hit / million) * cache_price_in
    if cache_price_out > 0 and cache_write_tokens > 0:
        cost += (int(cache_write_tokens) / million) * cache_price_out
    return round(cost, 6)


def _rule_is_active(rule: dict[str, Any], request_at: str) -> bool:
    try:
        current = datetime.fromisoformat(request_at)
    except (TypeError, ValueError):
        return False
    for key, compare in (
        ("effective_from", lambda value: current < value),
        ("effective_to", lambda value: current >= value),
    ):
        raw = str(rule.get(key) or "").strip()
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(raw)
        except ValueError:
            return False
        if compare(value):
            return False
    return True


def compute_model_rule_cost(
    rule: dict[str, Any],
    *,
    request_at: str,
    monthly_tokens_before: int,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> tuple[float, dict[str, Any] | None]:
    """计算一条已选费用规则；未生效或非法规则返回零费用。"""
    if not isinstance(rule, dict) or not _rule_is_active(rule, request_at):
        return 0.0, None
    kind = str(rule.get("kind") or "").strip()
    rule_id = str(rule.get("id") or "").strip()
    snapshot: dict[str, Any] = {"rule_id": rule_id, "kind": kind}
    if kind == "per_request":
        return round(_nonneg_float(rule.get("price_per_request")), 6), snapshot
    price = rule
    if kind == "token_tiered":
        tiers = rule.get("tiers")
        if not isinstance(tiers, list):
            return 0.0, None
        price = {}
        prior = max(0, int(monthly_tokens_before))
        for index, tier in enumerate(tiers):
            if not isinstance(tier, dict):
                continue
            limit = tier.get("up_to_tokens")
            if limit is None or prior < max(0, int(limit)):
                price = tier
                snapshot["tier_index"] = index
                break
        if not price:
            return 0.0, None
    elif kind != "token":
        return 0.0, None
    normalized = normalize_model_price_row(price)
    if normalized is None:
        return 0.0, None
    return (
        compute_usage_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            price_in=normalized["price_in"],
            price_out=normalized["price_out"],
            cache_price_in=normalized["cache_price_in"],
            cache_price_out=normalized["cache_price_out"],
        ),
        snapshot,
    )


def lookup_model_price(
    *,
    provider_id: str | None,
    model: str | None,
    doc: dict[str, Any] | None = None,
) -> tuple[dict[str, float] | None, str]:
    """返回 (单价行, 费用币种)；无配置时单价为 None。"""
    from pallas.product.llm.providers_store import load_providers_document

    payload = doc if isinstance(doc, dict) else load_providers_document()
    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    currency = normalize_cost_currency(routing.get("cost_currency") if isinstance(routing, dict) else "")
    pid = str(provider_id or "").strip()
    model_key = str(model or "").strip()
    if not pid or not model_key:
        return None, currency
    for row in payload.get("providers") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "").strip() != pid:
            continue
        pricing = row.get("model_pricing") if isinstance(row.get("model_pricing"), dict) else {}
        price = pricing.get(model_key)
        if price is None:
            # 忽略大小写再试一次
            lower = model_key.lower()
            for key, value in pricing.items():
                if str(key).strip().lower() == lower:
                    price = value
                    break
        normalized = normalize_model_price_row(price)
        return normalized, currency
    return None, currency


def cost_for_usage(
    *,
    provider_id: str | None,
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    request_at: str | None = None,
    monthly_tokens_before: int = 0,
    doc: dict[str, Any] | None = None,
) -> tuple[float, str]:
    if isinstance(doc, dict):
        payload = doc
    else:
        from pallas.product.llm.providers_store import load_providers_document

        payload = load_providers_document()
    if payload is not None:
        pid = str(provider_id or "").strip()
        model_name = str(model or "").strip()
        for provider in payload.get("providers") or []:
            if not isinstance(provider, dict) or str(provider.get("id") or "").strip() != pid:
                continue
            for registered in provider.get("models") or []:
                if not isinstance(registered, dict) or str(registered.get("name") or "").strip() != model_name:
                    continue
                rules = registered.get("pricing_rules")
                if not isinstance(rules, list):
                    break
                current = request_at or datetime.now().astimezone().isoformat()
                for rule in sorted(
                    (item for item in rules if isinstance(item, dict)),
                    key=lambda item: int(item.get("priority") or 0),
                    reverse=True,
                ):
                    cost, snapshot = compute_model_rule_cost(
                        rule,
                        request_at=current,
                        monthly_tokens_before=monthly_tokens_before,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cache_read_tokens=cache_read_tokens,
                        cache_write_tokens=cache_write_tokens,
                    )
                    if snapshot is not None:
                        _, currency = lookup_model_price(provider_id=provider_id, model=model, doc=payload)
                        return cost, currency
    price, currency = lookup_model_price(provider_id=provider_id, model=model, doc=doc)
    if price is None:
        return 0.0, currency
    return (
        compute_usage_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            price_in=price["price_in"],
            price_out=price["price_out"],
            cache_price_in=price["cache_price_in"],
            cache_price_out=price["cache_price_out"],
        ),
        currency,
    )


def estimate_tokens_cost_from_breakdown(
    tokens: dict[str, Any] | None,
    *,
    doc: dict[str, Any] | None = None,
) -> tuple[float, str]:
    """按 by_model 用量与当前单价估算费用（用于落盘 cost 为 0 时的展示回填）。"""
    from pallas.product.llm.providers_store import load_providers_document

    raw = tokens if isinstance(tokens, dict) else {}
    payload = doc if isinstance(doc, dict) else load_providers_document()
    routing = payload.get("routing") if isinstance(payload.get("routing"), dict) else {}
    currency = normalize_cost_currency(routing.get("cost_currency") if isinstance(routing, dict) else "")

    by_model = raw.get("by_model") if isinstance(raw.get("by_model"), dict) else {}
    by_provider = raw.get("by_provider") if isinstance(raw.get("by_provider"), dict) else {}
    provider_ids: list[str] = []
    seen: set[str] = set()

    def _push_pid(pid: str) -> None:
        key = str(pid or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        provider_ids.append(key)

    for pid, _row in sorted(
        by_provider.items(),
        key=lambda item: (
            -(
                int((item[1] or {}).get("total_tokens") or 0)
                + int((item[1] or {}).get("prompt_tokens") or 0)
                + int((item[1] or {}).get("completion_tokens") or 0)
                if isinstance(item[1], dict)
                else 0
            )
        ),
    ):
        _push_pid(str(pid))
    for row in payload.get("providers") or []:
        if isinstance(row, dict):
            _push_pid(str(row.get("id") or ""))

    total = 0.0
    for model, metrics in by_model.items():
        if not isinstance(metrics, dict):
            continue
        model_key = str(model or "").strip()
        if not model_key:
            continue
        price: dict[str, float] | None = None
        for pid in provider_ids:
            found, cur = lookup_model_price(provider_id=pid, model=model_key, doc=payload)
            if cur and not currency:
                currency = cur
            if found is not None:
                price = found
                break
        if price is None:
            continue
        total += compute_usage_cost(
            prompt_tokens=int(metrics.get("prompt_tokens") or 0),
            completion_tokens=int(metrics.get("completion_tokens") or 0),
            cache_read_tokens=int(metrics.get("cache_read_tokens") or 0),
            cache_write_tokens=int(metrics.get("cache_write_tokens") or 0),
            price_in=price["price_in"],
            price_out=price["price_out"],
            cache_price_in=price["cache_price_in"],
            cache_price_out=price["cache_price_out"],
        )
    return round(total, 6), currency


def enrich_tokens_cost_fields(
    tokens: dict[str, Any] | None,
    *,
    doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """保留已有 cost；若为 0 则按当前单价从 breakdown 回填。"""
    out = dict(tokens) if isinstance(tokens, dict) else {}
    try:
        stored = float(out.get("cost_total") or 0)
    except (TypeError, ValueError):
        stored = 0.0
    if stored != stored or stored < 0:  # NaN / negative
        stored = 0.0
    currency = normalize_cost_currency(out.get("cost_currency"))
    if stored > 0:
        out["cost_total"] = stored
        if currency:
            out["cost_currency"] = currency
        elif not out.get("cost_currency"):
            _, cur = estimate_tokens_cost_from_breakdown(out, doc=doc)
            if cur:
                out["cost_currency"] = cur
        return out
    estimated, cur = estimate_tokens_cost_from_breakdown(out, doc=doc)
    out["cost_total"] = estimated if estimated > 0 else 0.0
    if cur:
        out["cost_currency"] = cur
    elif currency:
        out["cost_currency"] = currency
    return out
