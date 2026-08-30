"""Read-side price queries that preserve provider and model identity boundaries."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PriceSnapshot, Provider, ProviderModel


def _source_input_price(price: PriceSnapshot) -> tuple[str, Decimal] | None:
    if price.normalized_usd_price and price.normalized_usd_price.get("input") is not None:
        return "USD/1M_tokens", Decimal(str(price.normalized_usd_price["input"]))
    if price.original_price:
        if price.original_price.get("input") is not None:
            return str(price.original_price.get("unit") or price.original_currency), Decimal(str(price.original_price["input"]))
        pricing = price.original_price.get("pricing")
        if isinstance(pricing, dict) and pricing.get("prompt") is not None:
            return str(price.original_price.get("unit") or price.original_currency), Decimal(str(pricing["prompt"]))
    if price.input_price is not None:
        return f"{price.currency}/1M_tokens", price.input_price
    return None


def _price_payload(provider: Provider, model: ProviderModel, price: PriceSnapshot) -> dict[str, object]:
    return {
        "provider_id": provider.provider_id,
        "provider_name": provider.display_name,
        "provider_model_id": model.provider_model_id,
        "provider_model_name": model.provider_model_name,
        "canonical_model_id": model.canonical_model_id,
        "input_price": str(price.input_price) if price.input_price is not None else None,
        "output_price": str(price.output_price) if price.output_price is not None else None,
        "cached_input_price": str(price.cached_input_price) if price.cached_input_price is not None else None,
        "cache_write_price": str(price.cache_write_price) if price.cache_write_price is not None else None,
        "currency": price.currency,
        "captured_at": price.captured_at,
        "source_url": price.source_url,
    }


def latest_price_comparison(session: Session, canonical_model_id: str) -> list[dict[str, object]]:
    """Return one latest snapshot per provider model for an explicitly mapped model."""
    items = session.execute(select(ProviderModel, Provider).join(
        Provider, Provider.id == ProviderModel.provider_id
    ).where(ProviderModel.canonical_model_id == canonical_model_id)).all()
    rows: list[dict[str, object]] = []
    for model, provider in items:
        price = session.scalar(select(PriceSnapshot).where(
            PriceSnapshot.provider_model_id == model.id
        ).order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc()).limit(1))
        if price is not None and price.validation_status in {"verified", "partial"} and price.identity_status in {"verified", "mapped"}:
            rows.append(_price_payload(provider, model, price))
    return sorted(rows, key=lambda item: Decimal(item["input_price"]) if item["input_price"] is not None else Decimal("Infinity"))


def price_history(session: Session, provider_id: str, provider_model_id: str, limit: int) -> list[dict[str, object]]:
    row = session.execute(select(ProviderModel, Provider).join(
        Provider, Provider.id == ProviderModel.provider_id
    ).where(Provider.provider_id == provider_id, ProviderModel.provider_model_id == provider_model_id)).first()
    if row is None:
        return []
    model, provider = row
    prices = session.scalars(select(PriceSnapshot).where(
        PriceSnapshot.provider_model_id == model.id
    ).order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc()).limit(limit)).all()
    return [_price_payload(provider, model, price) for price in prices]


def recent_price_changes(session: Session, limit: int) -> list[dict[str, object]]:
    """Compare the latest two snapshots per provider-native model.

    No change is inferred for unavailable or negative prices. A single snapshot
    is classified as new rather than as a price movement.
    """
    changes: list[dict[str, object]] = []
    rows = session.execute(select(ProviderModel, Provider).join(
        Provider, Provider.id == ProviderModel.provider_id
    )).all()
    for model, provider in rows:
        snapshots = session.scalars(select(PriceSnapshot).where(
            PriceSnapshot.provider_model_id == model.id
        ).order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc()).limit(2)).all()
        if not snapshots:
            continue
        latest = snapshots[0]
        if latest.validation_status not in {"verified", "partial"} or latest.identity_status not in {"verified", "mapped"}:
            continue
        payload = _price_payload(provider, model, latest)
        payload["previous_input_price"] = None
        payload["change_type"] = "new" if len(snapshots) == 1 else "unchanged"
        payload["input_price_delta"] = None
        if len(snapshots) == 2:
            previous = snapshots[1]
            latest_source = _source_input_price(latest)
            previous_source = _source_input_price(previous)
            if latest_source and previous_source and latest_source[0] == previous_source[0]:
                source_delta = latest_source[1] - previous_source[1]
                payload["previous_input_price"] = str(previous.input_price)
                if source_delta == 0:
                    payload["input_price_delta"] = str(Decimal(0))
                    payload["change_type"] = "unchanged"
                elif latest.input_price is not None and previous.input_price is not None:
                    payload["input_price_delta"] = str(latest.input_price - previous.input_price)
                    payload["change_type"] = "increased" if source_delta > 0 else "decreased"
        changes.append(payload)
    changed_first = {"decreased": 0, "increased": 1, "new": 2, "unchanged": 3}
    return sorted(changes, key=lambda row: (changed_first[row["change_type"]], row["provider_name"], row["provider_model_name"]))[:limit]
