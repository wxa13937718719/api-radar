from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Provider(Base):
    __tablename__ = "providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    homepage: Mapped[str | None] = mapped_column(String(500))
    pricing_source: Mapped[str | None] = mapped_column(String(500))
    official_url: Mapped[str | None] = mapped_column(String(500))
    pricing_url: Mapped[str | None] = mapped_column(String(500))
    api_base_url: Mapped[str | None] = mapped_column(String(500))
    provider_type: Mapped[str] = mapped_column(String(50), default="api_provider")
    country_or_region: Mapped[str | None] = mapped_column(String(100))
    discovery_source: Mapped[str | None] = mapped_column(String(500))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="supported", index=True)
    parser_status: Mapped[str] = mapped_column(String(30), default="ready")
    has_pricing_page: Mapped[bool] = mapped_column(Boolean, default=False)
    has_model_api: Mapped[bool] = mapped_column(Boolean, default=False)
    login_required: Mapped[bool] = mapped_column(Boolean, default=False)
    data_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.5"))
    priority_score: Mapped[int] = mapped_column(Integer, default=0)
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    adapter_name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    provider_models: Mapped[list[ProviderModel]] = relationship(back_populates="provider")
    prices: Mapped[list[PriceSnapshot]] = relationship(back_populates="provider")
    promotions: Mapped[list[Promotion]] = relationship(back_populates="provider")


class Model(Base):
    __tablename__ = "models"
    canonical_model_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200))
    model_family: Mapped[str | None] = mapped_column(String(100))
    vendor: Mapped[str | None] = mapped_column(String(100))
    context_length: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    provider_models: Mapped[list[ProviderModel]] = relationship(back_populates="model")
    aliases: Mapped[list[ModelAlias]] = relationship(back_populates="model")
    quality_profiles: Mapped[list[ModelQualityProfile]] = relationship(
        back_populates="model", cascade="all, delete-orphan"
    )


class ModelQualityProfile(Base):
    """Evidence-backed capability score for a canonical model.

    Scores are never inferred from a provider price or a display-name token.
    A missing row means that the capability is unknown, not average or high.
    """

    __tablename__ = "model_quality_profiles"
    __table_args__ = (UniqueConstraint("canonical_model_id", "capability", name="uq_model_quality_capability"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_model_id: Mapped[str] = mapped_column(ForeignKey("models.canonical_model_id"), index=True)
    capability: Mapped[str] = mapped_column(String(50), index=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    source: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    model: Mapped[Model] = relationship(back_populates="quality_profiles")


class ProviderModel(Base):
    __tablename__ = "provider_models"
    __table_args__ = (UniqueConstraint("provider_id", "provider_model_id", name="uq_provider_model"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    canonical_model_id: Mapped[str | None] = mapped_column(ForeignKey("models.canonical_model_id"), index=True)
    provider_model_id: Mapped[str] = mapped_column(String(300))
    provider_model_name: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str | None] = mapped_column(String(200))
    model_family: Mapped[str | None] = mapped_column(String(100))
    vendor: Mapped[str | None] = mapped_column(String(100))
    context_length: Mapped[int | None] = mapped_column(Integer)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    provider: Mapped[Provider] = relationship(back_populates="provider_models")
    model: Mapped[Model | None] = relationship(back_populates="provider_models")
    prices: Mapped[list[PriceSnapshot]] = relationship(back_populates="provider_model")


class ModelAlias(Base):
    __tablename__ = "model_aliases"
    __table_args__ = (UniqueConstraint("alias", "provider_id", name="uq_alias_provider"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(300), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"), index=True)
    canonical_model_id: Mapped[str] = mapped_column(ForeignKey("models.canonical_model_id"), index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1.0"))
    source: Mapped[str] = mapped_column(String(100), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model: Mapped[Model] = relationship(back_populates="aliases")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    provider_model_id: Mapped[int] = mapped_column(ForeignKey("provider_models.id"), index=True)
    canonical_model_id: Mapped[str | None] = mapped_column(ForeignKey("models.canonical_model_id"), index=True)
    provider_model_external_id: Mapped[str | None] = mapped_column(String(300))
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    cached_input_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    cache_write_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    currency: Mapped[str] = mapped_column(String(10))
    original_currency: Mapped[str | None] = mapped_column(String(10))
    original_price: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    normalized_usd_price: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    normalized_rmb_price: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    exchange_rate_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    identity_status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1.0"))
    invalid_reason: Mapped[str | None] = mapped_column(String(300))
    provider: Mapped[Provider] = relationship(back_populates="prices")
    provider_model: Mapped[ProviderModel] = relationship(back_populates="prices")


class ModelPrice(Base):
    """Latest normalized price for one model on one platform.

    PriceSnapshot remains the immutable audit trail.  This table is the small,
    query-friendly price board used by the decision centre.
    """

    __tablename__ = "model_price"
    __table_args__ = (UniqueConstraint("provider", "model", name="uq_model_price_provider_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    model: Mapped[str] = mapped_column(String(300), index=True)
    canonical_model_id: Mapped[str | None] = mapped_column(String(200), index=True)
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    context_length: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(10))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_type: Mapped[str] = mapped_column(String(50), default="price_page")
    updated_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    identity_status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1.0"))
    invalid_reason: Mapped[str | None] = mapped_column(String(300))


class ProviderOffer(Base):
    """A canonical model offer at one provider, kept separate from model identity."""

    __tablename__ = "provider_offers"
    __table_args__ = (UniqueConstraint("provider_id", "canonical_model_id", "provider_model_id", name="uq_provider_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    canonical_model_id: Mapped[str] = mapped_column(ForeignKey("models.canonical_model_id"), index=True)
    provider_model_id: Mapped[str] = mapped_column(String(300))
    input_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    output_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    cache_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    currency: Mapped[str | None] = mapped_column(String(10))
    billing_unit: Mapped[str | None] = mapped_column(String(50))
    context_length: Mapped[int | None] = mapped_column(Integer)
    rate_limit: Mapped[str | None] = mapped_column(String(200))
    subscription: Mapped[str | None] = mapped_column(String(300))
    availability: Mapped[str | None] = mapped_column(String(100))
    interaction_mode: Mapped[str] = mapped_column(String(30), default="realtime", index=True)
    speed_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    stability_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    compatibility_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    channel_risk: Mapped[str] = mapped_column(String(20), default="unknown")
    identity_status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    validation_status: Mapped[str] = mapped_column(String(20), default="verified", index=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("1.0"))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class ProviderDiscovery(Base):
    """Search/discovery evidence that can exist before an adapter is available."""

    __tablename__ = "provider_discoveries"
    __table_args__ = (UniqueConstraint("provider_id", "source_url", name="uq_provider_discovery_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    source_url: Mapped[str] = mapped_column(String(1000))
    source_type: Mapped[str] = mapped_column(String(50), default="search")
    query: Mapped[str | None] = mapped_column(String(500))
    evidence: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserAsset(Base):
    """A local record of accounts the user can already use; never stores a key."""

    __tablename__ = "user_assets"
    __table_args__ = (UniqueConstraint("provider", name="uq_user_asset_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    api_key_status: Mapped[str] = mapped_column(String(30), default="unknown")
    balance: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    currency: Mapped[str | None] = mapped_column(String(10))
    plan: Mapped[str | None] = mapped_column(String(300))
    available_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    has_account: Mapped[bool] = mapped_column(Boolean, default=False)
    credit_exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    subscription: Mapped[str | None] = mapped_column(String(300))
    primary_or_backup: Mapped[str] = mapped_column(String(20), default="primary")
    notes: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class LocalModelRegistry(Base):
    """Models actually available in a local runtime such as LM Studio."""

    __tablename__ = "local_model_registry"
    __table_args__ = (UniqueConstraint("runtime", "model", name="uq_local_runtime_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(300), index=True)
    quant: Mapped[str | None] = mapped_column(String(100))
    context: Mapped[int | None] = mapped_column(Integer)
    runtime: Mapped[str] = mapped_column(String(100), default="lm_studio", index=True)
    loaded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    benchmark: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    tokens_per_second: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    memory_usage: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Promotion(Base):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    promotion_type: Mapped[str] = mapped_column(String(100))
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discount: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    free_credit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    requirements: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(1000))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.5"))
    provider: Mapped[Provider | None] = relationship(back_populates="promotions")


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str | None] = mapped_column(String(500))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    fetch_success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    safe_raw_response: Mapped[str | None] = mapped_column(Text)
    snapshots: Mapped[list[SourceSnapshot]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    safe_text: Mapped[str | None] = mapped_column(Text)
    fetch_success: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_since_previous: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    source: Mapped[Source] = relationship(back_populates="snapshots")


class IntelligenceInsight(Base):
    """Human-facing interpretation of a source snapshot.

    ``safe_text``/``safe_raw_response`` remain backend-only evidence.  The UI
    consumes this table's summary, impact level and action instead of raw page
    text or provider responses.
    """

    __tablename__ = "intelligence_insights"
    __table_args__ = (UniqueConstraint("source_snapshot_id", name="uq_insight_snapshot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("source_snapshots.id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    impact_level: Mapped[str] = mapped_column(String(20), default="low", index=True)
    action: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(30), default="rules")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped[str] = mapped_column(String(50), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id"), index=True)
    canonical_model_id: Mapped[str | None] = mapped_column(ForeignKey("models.canonical_model_id"), index=True)
    total_score: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    dimension_scores: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class UserPreference(Base):
    """Single-user recommendation choices inferred from the local assistant chat."""

    __tablename__ = "user_preferences"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    preferred_profile: Mapped[str] = mapped_column(String(50), default="daily_chat")
    priorities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="running")
    triggered_by: Mapped[str] = mapped_column(String(50), default="manual")
    error: Mapped[str | None] = mapped_column(Text)
    results: Mapped[list[ScanResult]] = relationship(back_populates="scan_run", cascade="all, delete-orphan")


class ScanResult(Base):
    __tablename__ = "scan_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    scan_run_id: Mapped[str] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    models_count: Mapped[int] = mapped_column(Integer, default=0)
    price_changes_count: Mapped[int] = mapped_column(Integer, default=0)
    promotions_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    scan_run: Mapped[ScanRun] = relationship(back_populates="results")
