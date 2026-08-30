"""OpenRouter public catalog adapter.

Source: https://openrouter.ai/api/v1/models. Its documented pricing values are
USD per token, so this adapter converts them to USD/CNY per one million tokens.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .base import BaseProvider, NormalizedModel, NormalizedPrice, ProviderMetadata

MILLION = Decimal(1000000)
MODELS_URL = "https://openrouter.ai/api/v1/models"
FX_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=CNY"


def as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"OpenRouter returned an invalid price: {value!r}") from exc


class OpenRouterProvider(BaseProvider):
    metadata = ProviderMetadata(
        provider_id="openrouter",
        display_name="OpenRouter",
        homepage="https://openrouter.ai",
        pricing_source=MODELS_URL,
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _get_json(self, url: str) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.get(url)
        else:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("OpenRouter returned a non-object JSON response")
        return payload

    async def fetch_models(self) -> list[NormalizedModel]:
        payload = await self._get_json(MODELS_URL)
        data = payload.get("data")
        if not isinstance(data, list):
            raise TypeError("OpenRouter response has no data array")
        return [self.normalize_model(item) for item in data if isinstance(item, dict)]

    async def fetch_prices(self) -> list[NormalizedPrice]:
        payload = await self._get_json(MODELS_URL)
        data = payload.get("data")
        if not isinstance(data, list):
            raise TypeError("OpenRouter response has no data array")
        cny_rate, rate_timestamp = await self._fetch_usd_cny_rate()
        return [
            self.normalize_price(item, cny_rate=cny_rate, rate_timestamp=rate_timestamp)
            for item in data
            if isinstance(item, dict) and isinstance(item.get("pricing"), dict)
        ]

    async def _fetch_usd_cny_rate(self) -> tuple[Decimal, datetime]:
        payload = await self._get_json(FX_URL)
        rates = payload.get("rates")
        rate = rates.get("CNY") if isinstance(rates, dict) else None
        decimal_rate = as_decimal(rate)
        if decimal_rate is None or decimal_rate <= 0:
            raise ValueError("Exchange-rate source did not return a positive USD/CNY rate")
        return decimal_rate, datetime.now(UTC)

    def normalize_model(self, raw: Any) -> NormalizedModel:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise TypeError("OpenRouter model is missing its string id")
        provider_model_id = raw["id"]
        canonical_slug = raw.get("canonical_slug")
        # OpenRouter publishes canonical_slug. Use it only when it is explicitly supplied;
        # do not infer identity from a display name.
        canonical_model_id = canonical_slug if isinstance(canonical_slug, str) else None
        architecture = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
        return NormalizedModel(
            provider_model_id=provider_model_id,
            provider_model_name=str(raw.get("name") or provider_model_id),
            canonical_model_id=canonical_model_id,
            display_name=raw.get("name") if isinstance(raw.get("name"), str) else None,
            model_family=provider_model_id.split("/", 1)[-1].split(":", 1)[0],
            vendor=provider_model_id.split("/", 1)[0] if "/" in provider_model_id else None,
            context_length=raw.get("context_length") if isinstance(raw.get("context_length"), int) else None,
            capabilities={
                "input_modalities": architecture.get("input_modalities", []),
                "output_modalities": architecture.get("output_modalities", []),
                "supported_parameters": raw.get("supported_parameters", []),
            },
            raw_data=raw,
        )

    def normalize_price(
        self,
        raw: Any,
        *,
        cny_rate: Decimal = Decimal(1),
        rate_timestamp: datetime | None = None,
    ) -> NormalizedPrice:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            raise TypeError("OpenRouter price is missing its string model id")
        pricing = raw.get("pricing")
        if not isinstance(pricing, dict):
            raise TypeError(f"OpenRouter model {raw['id']} has no pricing object")

        def per_million(key: str) -> Decimal | None:
            value = as_decimal(pricing.get(key))
            return value * MILLION if value is not None else None

        usd = {
            "input": per_million("prompt"),
            "output": per_million("completion"),
            "cached_input": per_million("input_cache_read"),
            "cache_write": per_million("input_cache_write"),
        }
        cny = {key: value * cny_rate if value is not None else None for key, value in usd.items()}
        serialize = lambda values: {key: str(value) for key, value in values.items() if value is not None}
        return NormalizedPrice(
            provider_model_id=raw["id"],
            input_price=cny["input"],
            output_price=cny["output"],
            cached_input_price=cny["cached_input"],
            cache_write_price=cny["cache_write"],
            currency="CNY",
            original_currency="USD",
            original_price={"unit": "USD/token", "pricing": pricing},
            normalized_usd_price={"unit": "USD/1M_tokens", **serialize(usd)},
            normalized_rmb_price={"unit": "CNY/1M_tokens", **serialize(cny)},
            exchange_rate=cny_rate,
            exchange_rate_timestamp=rate_timestamp,
            source_url=MODELS_URL,
            raw_data={"pricing": pricing},
        )

    async def health_check(self) -> bool:
        try:
            payload = await self._get_json(MODELS_URL)
            return isinstance(payload.get("data"), list)
        except (httpx.HTTPError, TypeError, ValueError):
            return False


from .registry import registry

registry.register(OpenRouterProvider)
