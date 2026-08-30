from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api_radar.db import Base
from api_radar.models import (
    LocalModelRegistry,
    Model,
    ModelPrice,
    ModelQualityProfile,
    Provider,
    ProviderModel,
    ProviderOffer,
    UserAsset,
)
from api_radar.services.recommendations import decision_recommendations


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def _provider(session: Session, provider_id: str, *, comparable: bool = True) -> Provider:
    provider = Provider(
        provider_id=provider_id,
        display_name=provider_id.title(),
        homepage=f"https://{provider_id}.example",
        adapter_name="test",
        status="supported" if comparable else "discovered",
        has_pricing_page=comparable,
        has_model_api=comparable,
    )
    session.add(provider)
    session.flush()
    return provider


def _offer(
    session: Session,
    provider: Provider,
    canonical_id: str,
    name: str,
    *,
    input_price: str,
    output_price: str,
    interaction_mode: str = "realtime",
    quality: int | None = None,
    speed: int = 80,
    stability: int = 80,
    compatibility: int = 80,
) -> None:
    model = session.get(Model, canonical_id)
    if model is None:
        model = Model(canonical_model_id=canonical_id, display_name=name, capabilities={})
        session.add(model)
        session.flush()
    provider_model = ProviderModel(
        provider_id=provider.id,
        provider_model_id=f"{provider.provider_id}/{canonical_id}",
        provider_model_name=name,
        canonical_model_id=canonical_id,
        capabilities={"supported_parameters": ["tools", "tool_choice"]},
    )
    session.add(provider_model)
    session.flush()
    session.add(
        ModelPrice(
            provider=provider.provider_id,
            model=provider_model.provider_model_id,
            canonical_model_id=canonical_id,
            input_price=Decimal(input_price),
            output_price=Decimal(output_price),
            currency="USD",
            validation_status="verified",
            identity_status="verified",
            confidence=Decimal(1),
        )
    )
    session.add(
        ProviderOffer(
            provider_id=provider.id,
            canonical_model_id=canonical_id,
            provider_model_id=provider_model.provider_model_id,
            interaction_mode=interaction_mode,
            speed_score=Decimal(speed),
            stability_score=Decimal(stability),
            compatibility_score=Decimal(compatibility),
        )
    )
    if quality is not None:
        session.add(
            ModelQualityProfile(
                canonical_model_id=canonical_id,
                capability="coding",
                score=Decimal(quality),
                source="benchmark:test",
                confidence="high",
            )
        )
    session.commit()


def test_quality_is_canonical_and_not_inflated_by_cheaper_provider() -> None:
    session = _session()
    expensive = _provider(session, "official")
    cheap = _provider(session, "packy")
    _offer(session, expensive, "claude-sonnet", "Claude Sonnet", input_price="10", output_price="20", quality=92)
    _offer(session, cheap, "claude-sonnet", "Claude Sonnet", input_price="1", output_price="2", quality=None)
    rows = decision_recommendations(session, profile="coding", mode="best_quality")
    assert len(rows) == 1
    assert rows[0]["ability_score"] == "92"
    assert rows[0]["provider_id"] == "packy"  # stage 2 chooses the cheaper verified offer
    session.close()


def test_missing_quality_is_low_confidence_and_not_fake_precision() -> None:
    session = _session()
    provider = _provider(session, "official")
    _offer(session, provider, "unknown-model", "Unknown Model", input_price="1", output_price="2")
    row = decision_recommendations(session, profile="coding")[0]
    assert row["ability_score"] == "数据不足"
    assert row["value_score"] == "数据不足"
    assert row["score"] is None
    assert row["score_confidence"] == "low"
    session.close()


def test_unknown_output_price_is_not_classified_as_free() -> None:
    session = _session()
    provider = _provider(session, "official")
    _offer(session, provider, "input-only", "Input Only", input_price="0", output_price="0")
    price = session.query(ModelPrice).one()
    price.output_price = None
    session.commit()
    assert decision_recommendations(session, profile="coding", mode="free") == []
    session.close()


def test_modes_separate_free_budget_assets_and_batch() -> None:
    session = _session()
    provider = _provider(session, "official")
    _offer(session, provider, "strong", "Strong Coder", input_price="5", output_price="10", quality=95)
    _offer(session, provider, "cheap", "Cheap Coder", input_price="0.1", output_price="0.2", quality=75)
    _offer(session, provider, "free", "Free Coder", input_price="0", output_price="0", quality=60)
    _offer(session, provider, "batch", "Batch Coder", input_price="0.01", output_price="0.02", interaction_mode="batch", quality=99)
    session.add(UserAsset(provider="official", api_key_status="active", has_account=True, balance=Decimal(10), available_models=["cheap"], enabled=True))
    session.commit()
    best = decision_recommendations(session, profile="coding", mode="best_quality")
    budget = decision_recommendations(session, profile="coding", mode="budget")
    free = decision_recommendations(session, profile="coding", mode="free")
    assets = decision_recommendations(session, profile="coding", mode="my_assets")
    assert best[0]["canonical_model_id"] == "strong"
    assert budget[0]["canonical_model_id"] == "cheap"
    assert free and all(item["is_free"] for item in free)
    assert assets[0]["canonical_model_id"] == "cheap"
    assert all(item["interaction_mode"] != "batch" for item in best + budget + free + assets)
    session.close()


def test_subscription_is_not_treated_as_realtime_api() -> None:
    session = _session()
    provider = _provider(session, "official")
    _offer(session, provider, "subscription-model", "Subscription Model", input_price="0", output_price="0", interaction_mode="subscription", quality=99)
    assert decision_recommendations(session, profile="coding", mode="balanced") == []
    assert decision_recommendations(session, profile="coding", mode="free") == []
    session.close()


def test_batch_suffix_isolated_even_when_legacy_offer_mode_is_default() -> None:
    session = _session()
    provider = _provider(session, "official")
    _offer(session, provider, "gpt-3.5-turbo:batch", "GPT-3.5 Turbo batch", input_price="1", output_price="1", quality=99)
    rows = decision_recommendations(session, profile="daily_chat", mode="balanced")
    assert rows == []
    session.close()


def test_vision_rejects_explicit_text_only_offer() -> None:
    session = _session()
    provider = _provider(session, "official")
    _offer(session, provider, "text-only", "Text Only", input_price="1", output_price="1", quality=90)
    provider_model = session.query(ProviderModel).filter_by(provider_id=provider.id).one()
    provider_model.capabilities = {"input_modalities": ["text"]}
    session.commit()
    assert decision_recommendations(session, profile="vision", mode="balanced") == []
    session.close()


def test_local_offline_only_returns_loaded_registry_models() -> None:
    session = _session()
    provider = _provider(session, "openrouter")
    _offer(session, provider, "cloud-model", "Cloud Model", input_price="0.1", output_price="0.2", quality=90)
    session.add_all([
        LocalModelRegistry(model="loaded-local", runtime="lm_studio", loaded=True, tokens_per_second=Decimal(30)),
        LocalModelRegistry(model="unloaded-local", runtime="lm_studio", loaded=False),
    ])
    session.commit()
    rows = decision_recommendations(session, profile="local_offline", mode="balanced")
    assert [item["model"] for item in rows] == ["loaded-local"]
    assert all(item["provider_id"] == "lm_studio" and item["interaction_mode"] == "local" for item in rows)
    assert all(item["provider_id"] != "openrouter" for item in rows)
    session.close()


def test_estimated_cost_uses_input_and_output_prices() -> None:
    session = _session()
    provider = _provider(session, "official")
    _offer(session, provider, "cost-model", "Cost Model", input_price="2", output_price="4", quality=90)
    row = decision_recommendations(session, profile="coding", mode="balanced")[0]
    # coding uses 120k input + 30k output tokens: 120k*2 + 30k*4 = $0.36
    assert row["estimated_cost"] == "0.36000000"
    session.close()


def test_coverage_lists_unverified_discovered_providers() -> None:
    session = _session()
    provider = _provider(session, "openrouter")
    _offer(session, provider, "coverage-model", "Coverage Model", input_price="1", output_price="1", quality=80)
    rows = decision_recommendations(session, profile="coding")
    coverage = rows[0]["coverage"]
    names = {item["name"] for item in coverage["uncovered"]}
    assert coverage["comparable_providers"] == 1
    assert {"Packy", "ModelFlare", "SubRouter"} <= names
    assert "当前已验证渠道中" in rows[0]["why"]
    session.close()
