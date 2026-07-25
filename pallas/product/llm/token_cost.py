"""LLM token 费用：按提供方模型单价计算（币种与画画统计一致，由配置声明）。"""

from __future__ import annotations

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
    """按百万 tokens 单价计费；prompt 为非缓存输入（与 token_usage 解析一致）。"""
    million = 1_000_000.0
    cost = 0.0
    if price_in > 0 and prompt_tokens > 0:
        cost += (prompt_tokens / million) * price_in
    if price_out > 0 and completion_tokens > 0:
        cost += (completion_tokens / million) * price_out
    if cache_price_in > 0 and cache_read_tokens > 0:
        cost += (cache_read_tokens / million) * cache_price_in
    if cache_price_out > 0 and cache_write_tokens > 0:
        cost += (cache_write_tokens / million) * cache_price_out
    return cost


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
    doc: dict[str, Any] | None = None,
) -> tuple[float, str]:
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
