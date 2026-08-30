from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    display_name: str
    homepage: str
    pricing_source: str | None = None


@dataclass
class NormalizedModel:
    provider_model_id: str
    provider_model_name: str
    canonical_model_id: str | None = None
    display_name: str | None = None
    model_family: str | None = None
    vendor: str | None = None
    context_length: int | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedPrice:
    provider_model_id: str
    input_price: Decimal | None
    output_price: Decimal | None
    currency: str
    cached_input_price: Decimal | None = None
    cache_write_price: Decimal | None = None
    original_currency: str | None = None
    original_price: dict[str, Any] | None = None
    normalized_usd_price: dict[str, Any] | None = None
    normalized_rmb_price: dict[str, Any] | None = None
    exchange_rate: Decimal | None = None
    exchange_rate_timestamp: datetime | None = None
    source_url: str | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """Provider adapters own all provider-specific HTTP, parsing and naming rules."""

    metadata: ProviderMetadata

    @abstractmethod
    async def fetch_models(self) -> list[NormalizedModel]:
        raise NotImplementedError

    @abstractmethod
    async def fetch_prices(self) -> list[NormalizedPrice]:
        raise NotImplementedError

    @abstractmethod
    def normalize_model(self, raw: Any) -> NormalizedModel:
        raise NotImplementedError

    @abstractmethod
    def normalize_price(self, raw: Any) -> NormalizedPrice:
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError

    async def discover(self) -> dict[str, Any]:
        """Optional discovery hook; adapters may expose richer source metadata."""
        return {"provider_id": self.metadata.provider_id, "status": "supported"}

    async def fetch_promotions(self) -> list[dict[str, Any]]:
        return []

    async def fetch_limits(self) -> list[dict[str, Any]]:
        return []
