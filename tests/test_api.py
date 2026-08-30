from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api_radar.app import create_app
from api_radar.config import get_settings
from api_radar.db import Base, get_session
from api_radar.models import PriceSnapshot, Provider, ProviderModel


def test_read_api_exposes_provider_prices_and_history(monkeypatch) -> None:
    monkeypatch.setenv("API_RADAR_LLM_ENABLED", "false")
    get_settings.cache_clear()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    provider = Provider(provider_id="test", display_name="Test Provider", homepage="https://example.test",
                        pricing_source="https://example.test/pricing", adapter_name="TestAdapter")
    session.add(provider)
    session.flush()
    model = ProviderModel(provider_id=provider.id, provider_model_id="test/model", provider_model_name="Test Model",
                          canonical_model_id="test-model")
    session.add(model)
    session.flush()
    session.add_all([PriceSnapshot(provider_id=provider.id, provider_model_id=model.id,
        provider_model_external_id=model.provider_model_id, input_price=Decimal(2), output_price=Decimal(4), currency="CNY",
        captured_at=datetime.now(UTC)), PriceSnapshot(provider_id=provider.id, provider_model_id=model.id,
        provider_model_external_id=model.provider_model_id, input_price=Decimal(1), output_price=Decimal(3), currency="CNY",
        captured_at=datetime.now(UTC))])
    session.commit()
    app = create_app()
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    assert client.get("/providers").json()[0]["provider_id"] == "test"
    assert client.get("/models", params={"unmapped_only": True}).json()["models"] == []
    assert client.get("/prices/compare/test-model").json()["prices"][0]["input_price"] == "1.00000000"
    assert len(client.get("/prices/history", params={"provider_id": "test", "provider_model_id": "test/model"}).json()["history"]) == 2
    change = client.get("/prices/changes").json()["changes"][0]
    assert change["change_type"] == "decreased"
    assert change["input_price_delta"] == "-1.00000000"
    response = client.post("/models/test/test%2Fmodel/identity", json={"canonical_model_id": "test-model-v2"})
    assert response.status_code == 200
    assert response.json()["canonical_model_id"] == "test-model-v2"
    assert client.get("/aliases").json()[0]["source"] == "manual"
    assert client.get("/recommendations/nope").status_code == 400
    briefing = client.get("/assistant/briefing")
    assert briefing.status_code == 200
    assert briefing.json()["source"] == "rules"
    chat = client.post("/assistant/chat", json={"messages": [{"role": "user", "content": "今天怎么选？"}]})
    assert chat.status_code == 200
    assert chat.json()["source"] == "rules"
    adjusted = client.post("/assistant/chat", json={"messages": [{"role": "user", "content": "今天优先低成本和工具调用"}]})
    assert adjusted.status_code == 200
    assert adjusted.json()["adjustment"]["updated"] == ["budget", "tools"]
    assert client.get("/preferences").json()["priorities"] == {"budget": 3, "tools": 3}
    preference = client.put("/preferences", json={"profile": "coding", "priorities": {"quality": 4}})
    assert preference.status_code == 200
    assert preference.json()["priorities"] == {"quality": 4}
    assert client.put("/preferences", json={"priorities": {"wrong": 1}}).status_code == 400
    price_board = client.get("/model-prices")
    assert price_board.status_code == 200
    assert price_board.json()["prices"][0]["model"] == "test/model"
    today = client.get("/decision/today")
    assert today.status_code == 200
    assert len(today.json()["recommendations"]) == 7
    assert today.json()["recommendations"][0]["recommendations"][0]["value_score"]
    asset = client.post("/assets", json={
        "provider": "test", "api_key_status": "active", "plan": "local test",
        "available_models": ["Test Model"],
    })
    assert asset.status_code == 200
    assert client.get("/assets").json()[0]["provider"] == "test"
    boosted = client.get("/decision/recommendations/coding").json()["recommendations"][0]
    assert boosted["asset_available"] is True
    assert "无需另行注册" in boosted["reason"]
    assert client.delete(f"/assets/{asset.json()['id']}").json() == {"deleted": True}
    assert client.get("/insights").status_code == 200
    session.close()
    get_settings.cache_clear()
