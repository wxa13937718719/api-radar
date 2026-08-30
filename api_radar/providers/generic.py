"""Fallback adapter contract for discovered providers without a parser.

It never invents prices. Callers can use it to track a candidate and later add
an explicit adapter once the provider's public format is understood.
"""
from __future__ import annotations

from typing import Any

from .base import BaseProvider, NormalizedModel, NormalizedPrice, ProviderMetadata


class GenericWebProviderAdapter(BaseProvider):
    def __init__(self, metadata: ProviderMetadata) -> None:
        self.metadata = metadata

    async def fetch_models(self) -> list[NormalizedModel]:
        return []

    async def fetch_prices(self) -> list[NormalizedPrice]:
        return []

    def normalize_model(self, raw: Any) -> NormalizedModel:
        raise NotImplementedError("Generic provider models require a provider-specific parser")

    def normalize_price(self, raw: Any) -> NormalizedPrice:
        raise NotImplementedError("Generic provider prices require a provider-specific parser")

    async def health_check(self) -> bool:
        return False

    async def discover(self) -> dict[str, Any]:
        return {"provider_id": self.metadata.provider_id, "status": "needs_parser",
                "homepage": self.metadata.homepage, "pricing_url": self.metadata.pricing_source}
