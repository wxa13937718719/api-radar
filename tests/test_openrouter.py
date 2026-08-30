import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from api_radar.db import Base
from api_radar.models import PriceSnapshot, ProviderModel, ScanResult
from api_radar.providers.openrouter import FX_URL, MODELS_URL, OpenRouterProvider
from api_radar.services.scanner import ProviderScanService


@pytest.fixture
def catalog() -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "openrouter_models.json").read_text())


@pytest.fixture
def adapter(catalog: dict) -> OpenRouterProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == MODELS_URL:
            return httpx.Response(200, json=catalog)
        if str(request.url) == FX_URL:
            return httpx.Response(200, json={"rates": {"CNY": 7.2}})
        return httpx.Response(404)
    return OpenRouterProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_openrouter_normalizes_per_token_usd_to_per_million_cny(adapter: OpenRouterProvider) -> None:
    prices = await adapter.fetch_prices()
    price = prices[0]
    assert price.currency == "CNY"
    assert price.input_price == Decimal("2.016")
    assert price.output_price == Decimal("3.024")
    assert price.cached_input_price == Decimal("0.2016")
    assert price.normalized_usd_price == {"unit": "USD/1M_tokens", "input": "0.28000000", "output": "0.42000000", "cached_input": "0.028000000", "cache_write": "0.28000000"}


async def test_openrouter_scan_persists_append_only_price_snapshot(adapter: OpenRouterProvider) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    run = await ProviderScanService(session).scan(adapter)
    assert run.status == "success"
    assert session.scalar(select(ScanResult)).models_count == 1
    assert session.scalar(select(ProviderModel)).canonical_model_id == "deepseek/deepseek-v3.2"
    snapshot = session.scalar(select(PriceSnapshot))
    assert snapshot.input_price == Decimal("2.01600000")
    assert snapshot.original_currency == "USD"
    assert snapshot.exchange_rate_timestamp is not None
