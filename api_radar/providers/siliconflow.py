"""SiliconFlow public pricing-page adapter.

The public API model endpoint requires an API token.  The pricing page embeds
model records in Next.js data; only the explicitly published input price is
captured.  Output/cache prices remain ``None`` when not published.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .base import BaseProvider, NormalizedModel, NormalizedPrice, ProviderMetadata

PRICING_URL = "https://siliconflow.cn/pricing"
MODELS_URL = "https://api.siliconflow.cn/v1/models"
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.DOTALL)
_RECORD_RE = re.compile(
    r'\{"modelId":"(?P<id>[^"]+)","modelName":"(?P<name>[^"]+)"'
    r'(?P<body>.*?)(?:"inputPrice":"(?P<input>[0-9]+(?:\.[0-9]+)?)"'
    r',"inputPriceUnit":"(?P<unit>[^"]+)")', re.DOTALL
)


class SiliconFlowProvider(BaseProvider):
    metadata = ProviderMetadata(
        provider_id="siliconflow",
        display_name="SiliconFlow",
        homepage="https://siliconflow.cn",
        pricing_source=PRICING_URL,
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    async def _get(self, url: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await client.get(url)

    async def _pricing_records(self) -> list[dict[str, Any]]:
        response = await self._get(PRICING_URL)
        response.raise_for_status()
        records: list[dict[str, Any]] = []
        for match in _PUSH_RE.finditer(response.text):
            try:
                decoded = json.loads('"' + match.group(1) + '"')
            except json.JSONDecodeError:
                continue
            for item in _RECORD_RE.finditer(decoded):
                records.append({"modelId": item.group("id"), "modelName": item.group("name"),
                                "inputPrice": item.group("input"), "inputPriceUnit": item.group("unit")})
        if not records:
            raise ValueError("SiliconFlow pricing page format unsupported: no model records found")
        return records

    async def fetch_models(self) -> list[NormalizedModel]:
        return [self.normalize_model(item) for item in await self._pricing_records()]

    async def fetch_prices(self) -> list[NormalizedPrice]:
        return [self.normalize_price(item) for item in await self._pricing_records()]

    def normalize_model(self, raw: Any) -> NormalizedModel:
        if not isinstance(raw, dict) or not raw.get("modelId") or not raw.get("modelName"):
            raise TypeError("SiliconFlow pricing record is missing modelId/modelName")
        name = str(raw["modelName"])
        vendor = name.split("/", 1)[0] if "/" in name else None
        return NormalizedModel(provider_model_id=str(raw["modelId"]), provider_model_name=name,
                               display_name=name, model_family=name.split("/")[-1], vendor=vendor,
                               raw_data=raw)

    def normalize_price(self, raw: Any) -> NormalizedPrice:
        if not isinstance(raw, dict) or not raw.get("modelId"):
            raise TypeError("SiliconFlow pricing record is missing modelId")
        try:
            input_price = Decimal(str(raw["inputPrice"]))
        except (KeyError, InvalidOperation, ValueError) as exc:
            raise ValueError("SiliconFlow returned an invalid input price") from exc
        unit = str(raw.get("inputPriceUnit") or "")
        if "M Tokens" not in unit:
            raise ValueError(f"SiliconFlow pricing unit unsupported: {unit!r}")
        return NormalizedPrice(provider_model_id=str(raw["modelId"]), input_price=input_price,
                               output_price=None, currency="CNY", original_currency="CNY",
                               original_price={"input": str(input_price), "unit": unit},
                               normalized_rmb_price={"unit": "CNY/1M_tokens", "input": str(input_price)},
                               source_url=PRICING_URL, raw_data=raw)

    async def health_check(self) -> bool:
        try:
            return bool(await self._pricing_records())
        except (httpx.HTTPError, ValueError):
            return False


from .registry import registry

registry.register(SiliconFlowProvider)
