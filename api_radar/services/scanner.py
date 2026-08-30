from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Model,
    ModelPrice,
    PriceSnapshot,
    Provider,
    ProviderModel,
    ProviderOffer,
    ScanResult,
    ScanRun,
)
from ..providers.base import BaseProvider, NormalizedModel, NormalizedPrice
from .validation import identity_status, validate_price


def utc_now() -> datetime:
    return datetime.now(UTC)


class ProviderScanService:
    """Persists normalized results while keeping each scan append-only for pricing."""

    def __init__(self, session: Session) -> None:
        self.session = session

    async def scan(self, adapter: BaseProvider, *, triggered_by: str = "manual") -> ScanRun:
        run = ScanRun(triggered_by=triggered_by)
        self.session.add(run)
        self.session.flush()
        provider = self._get_or_create_provider(adapter)
        result = ScanResult(scan_run_id=run.id, provider_id=provider.id, status="running")
        self.session.add(result)
        self.session.flush()
        try:
            models = await adapter.fetch_models()
            prices = await adapter.fetch_prices()
            provider_models = {model.provider_model_id: self._upsert_model(provider, model) for model in models}
            for price in prices:
                if price.provider_model_id in provider_models:
                    self._save_price(provider, provider_models[price.provider_model_id], price)
            result.models_count = len(models)
            result.price_changes_count = len(prices)
            result.status = "success"
            run.status = "success"
        except Exception as exc:  # noqa: BLE001 -- adapter isolation records all provider failures
            result.status = "failed"
            result.error = str(exc)
            run.status = "partial_failure"
            run.error = str(exc)
        finally:
            completed = utc_now()
            result.completed_at = completed
            run.completed_at = completed
            self.session.commit()
        return run

    def _get_or_create_provider(self, adapter: BaseProvider) -> Provider:
        provider = self.session.scalar(select(Provider).where(Provider.provider_id == adapter.metadata.provider_id))
        if provider is None:
            provider = Provider(
                provider_id=adapter.metadata.provider_id,
                display_name=adapter.metadata.display_name,
                homepage=adapter.metadata.homepage,
                pricing_source=adapter.metadata.pricing_source,
                adapter_name=type(adapter).__name__,
                official_url=adapter.metadata.homepage,
                pricing_url=adapter.metadata.pricing_source,
                status="supported", parser_status="ready", has_pricing_page=bool(adapter.metadata.pricing_source),
                has_model_api=True, data_confidence=Decimal("0.9"), last_checked_at=utc_now(),
            )
            self.session.add(provider)
            self.session.flush()
        provider.last_checked_at = utc_now()
        provider.status = "supported"
        provider.parser_status = "ready"
        provider.has_pricing_page = bool(adapter.metadata.pricing_source)
        provider.has_model_api = True
        return provider

    def _upsert_model(self, provider: Provider, model: NormalizedModel) -> ProviderModel:
        if model.canonical_model_id and self.session.get(Model, model.canonical_model_id) is None:
            self.session.add(Model(
                canonical_model_id=model.canonical_model_id,
                display_name=model.display_name or model.provider_model_name,
                model_family=model.model_family,
                vendor=model.vendor,
                context_length=model.context_length,
                capabilities=model.capabilities,
            ))
        item = self.session.scalar(select(ProviderModel).where(
            ProviderModel.provider_id == provider.id,
            ProviderModel.provider_model_id == model.provider_model_id,
        ))
        if item is None:
            item = ProviderModel(provider_id=provider.id, provider_model_id=model.provider_model_id,
                                 provider_model_name=model.provider_model_name)
            self.session.add(item)
        # Numeric provider IDs alone are not an identity. Keep them visible but
        # out of canonical comparisons until manually mapped.
        item.canonical_model_id = model.canonical_model_id if identity_status(model.provider_model_id) != "unresolved" else None
        item.display_name = model.display_name
        item.model_family = model.model_family
        item.vendor = model.vendor
        item.context_length = model.context_length
        item.capabilities = model.capabilities
        item.last_seen_at = utc_now()
        self.session.flush()
        return item

    def _save_price(self, provider: Provider, model: ProviderModel, price: NormalizedPrice) -> None:
        unit = None
        if isinstance(price.original_price, dict):
            unit = price.original_price.get("unit")
        validation, parsed_input, invalid_reason = validate_price(price.input_price, unit=unit, field="input_price")
        if validation == "verified" and price.output_price is None:
            validation = "partial"
        identity = identity_status(model.provider_model_id)
        if identity == "unresolved":
            validation = "unverified" if validation == "verified" else validation
            invalid_reason = invalid_reason or "provider model identity is unresolved"
        self.session.add(PriceSnapshot(
            provider_id=provider.id, provider_model_id=model.id, canonical_model_id=model.canonical_model_id,
            provider_model_external_id=price.provider_model_id, input_price=price.input_price,
            output_price=price.output_price, cached_input_price=price.cached_input_price,
            cache_write_price=price.cache_write_price, currency=price.currency,
            original_currency=price.original_currency, original_price=price.original_price,
            normalized_usd_price=price.normalized_usd_price, normalized_rmb_price=price.normalized_rmb_price,
            exchange_rate=price.exchange_rate, exchange_rate_timestamp=price.exchange_rate_timestamp,
            source_url=price.source_url, raw_data=price.raw_data,
            validation_status=validation, identity_status=identity,
            confidence=Decimal("0.9") if validation in {"verified", "partial"} and identity != "unresolved" else Decimal("0.2"),
            invalid_reason=invalid_reason,
        ))
        current = self.session.scalar(select(ModelPrice).where(
            ModelPrice.provider == provider.provider_id,
            ModelPrice.model == model.provider_model_id,
        ))
        if current is None:
            current = ModelPrice(provider=provider.provider_id, model=model.provider_model_id)
            self.session.add(current)
        current.canonical_model_id = model.canonical_model_id
        current.input_price = parsed_input
        current.output_price = price.output_price
        current.context_length = model.context_length
        current.currency = price.currency
        current.source_url = price.source_url or provider.pricing_source
        current.source_type = "provider_api"
        current.updated_time = utc_now()
        current.validation_status = validation
        current.identity_status = identity
        current.confidence = Decimal("0.9") if validation in {"verified", "partial"} and identity != "unresolved" else Decimal("0.2")
        current.invalid_reason = invalid_reason
        if model.canonical_model_id:
            offer = self.session.scalar(select(ProviderOffer).where(
                ProviderOffer.provider_id == provider.id,
                ProviderOffer.canonical_model_id == model.canonical_model_id,
                ProviderOffer.provider_model_id == model.provider_model_id,
            ))
            if offer is None:
                offer = ProviderOffer(provider_id=provider.id, canonical_model_id=model.canonical_model_id,
                                      provider_model_id=model.provider_model_id)
                self.session.add(offer)
            offer.input_price = parsed_input
            offer.output_price = price.output_price
            offer.cache_price = price.cached_input_price
            offer.currency = price.currency
            offer.billing_unit = unit
            offer.context_length = model.context_length
            # Provider metadata is offer-level evidence.  It must never alter
            # the canonical model's capability profile.
            raw_offer = price.raw_data or {}
            offer.interaction_mode = str(raw_offer.get("interaction_mode") or "realtime")
            offer.speed_score = raw_offer.get("speed_score")
            offer.stability_score = raw_offer.get("stability_score")
            offer.compatibility_score = raw_offer.get("compatibility_score")
            offer.channel_risk = str(raw_offer.get("channel_risk") or "unknown")
            offer.identity_status = identity
            offer.validation_status = validation
            offer.confidence = current.confidence
            offer.source_url = price.source_url
            offer.last_verified_at = utc_now()
