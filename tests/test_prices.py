from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api_radar.db import Base
from api_radar.models import PriceSnapshot, Provider, ProviderModel
from api_radar.services.prices import recent_price_changes


def test_exchange_rate_move_is_not_reported_as_provider_price_change() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    provider = Provider(provider_id="usd", display_name="USD Provider", adapter_name="Test")
    session.add(provider)
    session.flush()
    model = ProviderModel(provider_id=provider.id, provider_model_id="model", provider_model_name="Model")
    session.add(model)
    session.flush()
    session.add_all([
        PriceSnapshot(provider_id=provider.id, provider_model_id=model.id, input_price=Decimal("7.20"),
                      currency="CNY", normalized_usd_price={"input": "1.00"}, captured_at=datetime.now(UTC)),
        PriceSnapshot(provider_id=provider.id, provider_model_id=model.id, input_price=Decimal("7.10"),
                      currency="CNY", normalized_usd_price={"input": "1.00"}, captured_at=datetime.now(UTC)),
    ])
    session.commit()
    change = recent_price_changes(session, 1)[0]
    assert change["change_type"] == "unchanged"
    assert change["input_price_delta"] == "0"
    session.close()
