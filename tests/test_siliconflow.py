import json
from decimal import Decimal

import httpx
import pytest

from api_radar.providers.siliconflow import PRICING_URL, SiliconFlowProvider


@pytest.mark.asyncio
async def test_siliconflow_normalizes_public_input_price() -> None:
    payload = '{"modelId":"sf-1","modelName":"deepseek-ai/DeepSeek-V3","inputPrice":"2","inputPriceUnit":"/ M Tokens"}'
    html = '<script>self.__next_f.push([1,' + json.dumps(payload) + '])</script>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    adapter = SiliconFlowProvider(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    models = await adapter.fetch_models()
    prices = await adapter.fetch_prices()
    await adapter._client.aclose()
    assert models[0].provider_model_id == "sf-1"
    assert prices[0].input_price == Decimal(2)
    assert prices[0].output_price is None
    assert prices[0].currency == "CNY"
    assert prices[0].source_url == PRICING_URL
