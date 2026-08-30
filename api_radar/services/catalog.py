"""Catalog reads and explicit, user-confirmed model identity updates."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Model, ModelAlias, PriceSnapshot, Provider, ProviderModel


def list_provider_models(session: Session, *, unmapped_only: bool, limit: int) -> list[dict[str, object]]:
    statement = select(ProviderModel, Provider).join(Provider, Provider.id == ProviderModel.provider_id)
    if unmapped_only:
        statement = statement.where(ProviderModel.canonical_model_id.is_(None))
    rows = session.execute(statement.order_by(Provider.display_name, ProviderModel.provider_model_name).limit(limit)).all()
    results = []
    for item, provider in rows:
        price = session.scalar(select(PriceSnapshot).where(PriceSnapshot.provider_model_id == item.id).order_by(
            PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc()).limit(1))
        results.append({"provider_id": provider.provider_id, "provider_model_id": item.provider_model_id,
            "provider_model_name": item.provider_model_name, "canonical_model_id": item.canonical_model_id,
            "vendor": item.vendor, "model_family": item.model_family, "context_length": item.context_length,
            "capabilities": item.capabilities, "latest_input_price": str(price.input_price) if price and price.input_price is not None else None,
            "currency": price.currency if price else None})
    return results


def confirm_model_identity(session: Session, *, provider_id: str, provider_model_id: str,
                           canonical_model_id: str) -> ProviderModel | None:
    row = session.execute(select(ProviderModel, Provider).join(Provider, Provider.id == ProviderModel.provider_id).where(
        Provider.provider_id == provider_id, ProviderModel.provider_model_id == provider_model_id
    )).first()
    if row is None:
        return None
    item, provider = row
    canonical = session.get(Model, canonical_model_id)
    if canonical is None:
        canonical = Model(canonical_model_id=canonical_model_id,
            display_name=item.display_name or item.provider_model_name, model_family=item.model_family,
            vendor=item.vendor, context_length=item.context_length, capabilities=item.capabilities)
        session.add(canonical)
    item.canonical_model_id = canonical_model_id
    existing_alias = session.scalar(select(ModelAlias).where(
        ModelAlias.alias == item.provider_model_id, ModelAlias.provider_id == provider.id
    ))
    if existing_alias is None:
        session.add(ModelAlias(alias=item.provider_model_id, provider_id=provider.id,
            canonical_model_id=canonical_model_id, confidence=1, source="manual"))
    else:
        existing_alias.canonical_model_id = canonical_model_id
        existing_alias.confidence = 1
        existing_alias.source = "manual"
    session.commit()
    return item
