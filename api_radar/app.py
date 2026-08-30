# ruff: noqa: B008 -- FastAPI dependencies are declared in endpoint signatures.
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal, create_all, get_session
from .intelligence import backfill_insights
from .models import (
    IntelligenceInsight,
    LocalModelRegistry,
    Model,
    ModelAlias,
    ModelPrice,
    ModelQualityProfile,
    Promotion,
    Provider,
    ScanRun,
    Source,
    SourceSnapshot,
    UserAsset,
)

# Import adapters so their registry decorators run for API requests.
from .providers import openrouter as _openrouter  # noqa: F401
from .providers import siliconflow as _siliconflow  # noqa: F401
from .providers.registry import registry
from .services.assistant import briefing, chat
from .services.catalog import confirm_model_identity, list_provider_models
from .services.discovery import (
    market_coverage,
    prioritize_assets,
    provider_payload,
    record_discovery,
    seed_known_candidates,
)
from .services.prices import latest_price_comparison, price_history, recent_price_changes
from .services.recommendations import (
    PROFILES,
    RECOMMENDATION_MODES,
    daily_decision_center,
    decision_recommendations,
    generate_recommendations,
    get_user_preference,
    sync_price_board,
)
from .services.scan_jobs import run_intelligence_job, run_scan_job


class ModelIdentityRequest(BaseModel):
    canonical_model_id: str = Field(min_length=1, max_length=200, pattern=r"^[a-z0-9][a-z0-9._/-]*$")


class PromotionRequest(BaseModel):
    provider_id: int | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    promotion_type: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(default=1.0, ge=0, le=1)


class AssistantMessage(BaseModel):
    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class AssistantChatRequest(BaseModel):
    messages: list[AssistantMessage] = Field(min_length=1, max_length=20)
    profile: str = "daily_chat"


class PreferenceRequest(BaseModel):
    profile: str | None = None
    priorities: dict[str, int] | None = None


class UserAssetRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    api_key_status: str = Field(default="unknown", pattern=r"^(active|inactive|unknown)$")
    balance: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    plan: str | None = Field(default=None, max_length=300)
    available_models: list[str] = Field(default_factory=list, max_length=200)
    has_account: bool | None = None
    credit_exchange_rate: float | None = Field(default=None, ge=0)
    subscription: str | None = Field(default=None, max_length=300)
    primary_or_backup: str = Field(default="primary", pattern=r"^(primary|backup)$")
    notes: str | None = Field(default=None, max_length=4000)
    enabled: bool = True


class LocalModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=300)
    quant: str | None = Field(default=None, max_length=100)
    context: int | None = Field(default=None, ge=1)
    runtime: str = Field(default="lm_studio", max_length=100)
    loaded: bool = False
    benchmark: dict[str, object] | None = None
    tokens_per_second: float | None = Field(default=None, ge=0)
    memory_usage: float | None = Field(default=None, ge=0)


class ModelQualityRequest(BaseModel):
    canonical_model_id: str = Field(min_length=1, max_length=200)
    capability: str = Field(pattern=r"^(coding|reasoning|writing|chinese|long_context|vision|agent_tool_use|instruction_following)$")
    score: float | None = Field(default=None, ge=0, le=100)
    source: str = Field(min_length=1, max_length=200)
    confidence: str = Field(default="low", pattern=r"^(high|medium|low)$")


class DiscoveryRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    official_url: str = Field(min_length=1, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)
    source_type: str = Field(default="search", max_length=50)
    query: str | None = Field(default=None, max_length=500)
    evidence: str | None = Field(default=None, max_length=4000)


def asset_payload(item: UserAsset) -> dict[str, object]:
    return {"id": item.id, "provider": item.provider, "api_key_status": item.api_key_status,
            "balance": str(item.balance) if item.balance is not None else None, "currency": item.currency,
            "plan": item.plan, "available_models": item.available_models or [], "enabled": item.enabled,
            "has_account": item.has_account, "credit_exchange_rate": str(item.credit_exchange_rate) if item.credit_exchange_rate is not None else None,
            "subscription": item.subscription, "primary_or_backup": item.primary_or_backup, "notes": item.notes,
            "updated_at": item.updated_at}


def create_app() -> FastAPI:
    app = FastAPI(title="API Radar", version="0.1.0")

    @app.on_event("startup")
    def startup() -> None:
        create_all()
        with SessionLocal() as session:
            seed_known_candidates(session)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/providers")
    def providers(session: Session = Depends(get_session)) -> list[dict[str, object]]:
        seed_known_candidates(session)
        items = session.scalars(select(Provider).order_by(Provider.display_name)).all()
        return [provider_payload(p) for p in sorted(items, key=lambda item: (item.status != "supported", item.display_name))]

    @app.get("/provider-registry")
    def provider_registry(status: str | None = None, session: Session = Depends(get_session)) -> dict[str, object]:
        seed_known_candidates(session)
        statement = select(Provider).where(Provider.ignored.is_(False)).order_by(Provider.priority_score.desc(), Provider.display_name)
        if status:
            statement = statement.where(Provider.status == status)
        return {"providers": [provider_payload(p) for p in session.scalars(statement).all()],
                "coverage": market_coverage(session)}

    @app.get("/coverage")
    def coverage(session: Session = Depends(get_session)) -> dict[str, object]:
        seed_known_candidates(session)
        prioritize_assets(session)
        return market_coverage(session)

    @app.get("/provider-discoveries")
    def provider_discoveries(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)) -> list[dict[str, object]]:
        from .models import ProviderDiscovery
        rows = session.execute(select(ProviderDiscovery, Provider).join(
            Provider, Provider.id == ProviderDiscovery.provider_id
        ).order_by(ProviderDiscovery.captured_at.desc()).limit(limit)).all()
        return [{"provider_id": provider.provider_id, "provider": provider.display_name,
                 "source_url": item.source_url, "source_type": item.source_type, "query": item.query,
                 "evidence": item.evidence, "captured_at": item.captured_at} for item, provider in rows]

    @app.post("/provider-discoveries")
    def add_provider_discovery(request: DiscoveryRequest, session: Session = Depends(get_session)) -> dict[str, object]:
        from .services.discovery import _upsert
        provider = _upsert(session, request.provider_id.strip().casefold(), request.display_name.strip(),
                           request.official_url, None, request.source_type)
        session.flush()
        evidence_url = request.source_url or request.official_url
        record_discovery(session, provider, source_url=evidence_url, source_type=request.source_type,
                         query=request.query, evidence=request.evidence)
        session.commit()
        return provider_payload(provider)

    @app.get("/models")
    def models(unmapped_only: bool = False, limit: int = Query(100, ge=1, le=500),
               session: Session = Depends(get_session)) -> dict[str, object]:
        return {"models": list_provider_models(session, unmapped_only=unmapped_only, limit=limit)}

    @app.post("/models/{provider_id}/{provider_model_id:path}/identity")
    def confirm_identity(provider_id: str, provider_model_id: str, request: ModelIdentityRequest,
                         session: Session = Depends(get_session)) -> dict[str, object]:
        item = confirm_model_identity(session, provider_id=provider_id,
                                      provider_model_id=provider_model_id,
                                      canonical_model_id=request.canonical_model_id)
        if item is None:
            raise HTTPException(status_code=404, detail="provider model not found")
        return {"provider_id": provider_id, "provider_model_id": provider_model_id,
                "canonical_model_id": item.canonical_model_id, "source": "manual"}

    @app.get("/model-quality")
    def model_quality(canonical_model_id: str | None = None,
                      session: Session = Depends(get_session)) -> list[dict[str, object]]:
        statement = select(ModelQualityProfile).order_by(ModelQualityProfile.canonical_model_id,
                                                          ModelQualityProfile.capability)
        if canonical_model_id:
            statement = statement.where(ModelQualityProfile.canonical_model_id == canonical_model_id)
        return [{"canonical_model_id": item.canonical_model_id, "capability": item.capability,
                 "score": str(item.score) if item.score is not None else None, "source": item.source,
                 "confidence": item.confidence, "updated_at": item.updated_at}
                for item in session.scalars(statement).all()]

    @app.put("/model-quality")
    def upsert_model_quality(request: ModelQualityRequest,
                             session: Session = Depends(get_session)) -> dict[str, object]:
        if session.get(Model, request.canonical_model_id) is None:
            raise HTTPException(status_code=404, detail="canonical model not found")
        item = session.scalar(select(ModelQualityProfile).where(
            ModelQualityProfile.canonical_model_id == request.canonical_model_id,
            ModelQualityProfile.capability == request.capability,
        ))
        if item is None:
            item = ModelQualityProfile(canonical_model_id=request.canonical_model_id,
                                       capability=request.capability)
            session.add(item)
        item.score = request.score
        item.source = request.source
        item.confidence = request.confidence
        session.commit()
        return {"canonical_model_id": item.canonical_model_id, "capability": item.capability,
                "score": str(item.score) if item.score is not None else None,
                "source": item.source, "confidence": item.confidence, "updated_at": item.updated_at}

    @app.get("/aliases")
    def aliases(limit: int = Query(100, ge=1, le=500), session: Session = Depends(get_session)) -> list[dict[str, object]]:
        return [{"alias": item.alias, "canonical_model_id": item.canonical_model_id,
                 "provider_id": item.provider_id, "confidence": str(item.confidence), "source": item.source}
                for item in session.scalars(select(ModelAlias).order_by(ModelAlias.id.desc()).limit(limit)).all()]

    @app.get("/prices/changes")
    def price_changes(limit: int = Query(50, ge=1, le=500),
                      session: Session = Depends(get_session)) -> dict[str, object]:
        return {"changes": [item for item in recent_price_changes(session, limit * 2)
                             if item["change_type"] != "unchanged"][:limit]}

    @app.get("/model-prices")
    def model_prices(limit: int = Query(500, ge=1, le=2000), include_unverified: bool = False,
                     session: Session = Depends(get_session)) -> dict[str, object]:
        sync_price_board(session)
        statement = select(ModelPrice).order_by(ModelPrice.updated_time.desc())
        if not include_unverified:
            statement = statement.where(ModelPrice.validation_status.in_(["verified", "partial"]),
                                        ModelPrice.identity_status.in_(["verified", "mapped"]))
        rows = session.scalars(statement.limit(limit)).all()
        return {"prices": [{"provider": item.provider, "model": item.model,
                "canonical_model_id": item.canonical_model_id,
                "input_price": str(item.input_price) if item.input_price is not None else None,
                "output_price": str(item.output_price) if item.output_price is not None else None,
                "context_length": item.context_length, "currency": item.currency, "source_url": item.source_url,
                "source_type": item.source_type, "updated_time": item.updated_time,
                "validation_status": item.validation_status, "identity_status": item.identity_status,
                "confidence": str(item.confidence), "invalid_reason": item.invalid_reason} for item in rows]}

    @app.get("/prices/compare/{canonical_model_id:path}")
    def compare_prices(canonical_model_id: str, session: Session = Depends(get_session)) -> dict[str, object]:
        return {"canonical_model_id": canonical_model_id, "prices": latest_price_comparison(session, canonical_model_id)}

    @app.get("/prices/history")
    def history(provider_id: str, provider_model_id: str, limit: int = Query(30, ge=1, le=500),
                session: Session = Depends(get_session)) -> dict[str, object]:
        return {"provider_id": provider_id, "provider_model_id": provider_model_id,
                "history": price_history(session, provider_id, provider_model_id, limit)}

    @app.get("/recommendations/{profile}")
    def recommendations(profile: str, mode: str = "balanced", limit: int = Query(5, ge=1, le=50),
                        session: Session = Depends(get_session)) -> dict[str, object]:
        if profile not in PROFILES:
            raise HTTPException(status_code=400, detail=f"profile must be one of: {', '.join(PROFILES)}")
        if mode not in RECOMMENDATION_MODES:
            raise HTTPException(status_code=400, detail=f"mode must be one of: {', '.join(RECOMMENDATION_MODES)}")
        rows = generate_recommendations(session, profile=profile, mode=mode, limit=limit)
        return {"profile": profile, "mode": mode, "recommendations": [
            {"provider_id": r.provider_id, "canonical_model_id": r.canonical_model_id,
             "score": str(r.total_score), "dimensions": r.dimension_scores, "reason": r.reason}
            for r in rows]}

    @app.get("/decision/recommendations/{profile}")
    def decision_recommendation(profile: str, mode: str = "balanced", limit: int = Query(5, ge=1, le=20),
                                session: Session = Depends(get_session)) -> dict[str, object]:
        if profile not in PROFILES:
            raise HTTPException(status_code=400, detail=f"profile must be one of: {', '.join(PROFILES)}")
        if mode not in RECOMMENDATION_MODES:
            raise HTTPException(status_code=400, detail=f"mode must be one of: {', '.join(RECOMMENDATION_MODES)}")
        return {"profile": profile, "mode": mode, "recommendations": decision_recommendations(session, profile=profile, mode=mode, limit=limit)}

    @app.get("/decision/today")
    def today_decision(session: Session = Depends(get_session)) -> dict[str, object]:
        return daily_decision_center(session)

    @app.get("/assistant/briefing")
    async def assistant_briefing(profile: str = "daily_chat", session: Session = Depends(get_session)) -> dict[str, object]:
        if profile not in PROFILES:
            raise HTTPException(status_code=400, detail=f"profile must be one of: {', '.join(PROFILES)}")
        return await briefing(session, profile)

    @app.post("/assistant/chat")
    async def assistant_chat(request: AssistantChatRequest, session: Session = Depends(get_session)) -> dict[str, object]:
        if request.profile not in PROFILES:
            raise HTTPException(status_code=400, detail=f"profile must be one of: {', '.join(PROFILES)}")
        return await chat(session, [item.model_dump() for item in request.messages], request.profile)

    @app.get("/preferences")
    def preferences(session: Session = Depends(get_session)) -> dict[str, object]:
        preference = get_user_preference(session)
        return {"profile": preference.preferred_profile, "priorities": preference.priorities or {},
                "updated_at": preference.updated_at}

    @app.put("/preferences")
    def update_preferences(request: PreferenceRequest, session: Session = Depends(get_session)) -> dict[str, object]:
        preference = get_user_preference(session)
        if request.profile is not None:
            if request.profile not in PROFILES:
                raise HTTPException(status_code=400, detail=f"profile must be one of: {', '.join(PROFILES)}")
            preference.preferred_profile = request.profile
        if request.priorities is not None:
            invalid = [key for key, value in request.priorities.items() if key not in {"budget", "quality", "context", "tools"} or value < 0 or value > 4]
            if invalid:
                raise HTTPException(status_code=400, detail="priorities must use budget, quality, context, or tools with 0-4")
            preference.priorities = request.priorities
        session.commit()
        return {"profile": preference.preferred_profile, "priorities": preference.priorities or {},
                "updated_at": preference.updated_at}

    @app.get("/assets")
    def assets(session: Session = Depends(get_session)) -> list[dict[str, object]]:
        return [asset_payload(item) for item in session.scalars(select(UserAsset).order_by(UserAsset.provider)).all()]

    @app.post("/assets")
    def add_asset(request: UserAssetRequest, session: Session = Depends(get_session)) -> dict[str, object]:
        item = session.scalar(select(UserAsset).where(UserAsset.provider == request.provider.strip()))
        if item is None:
            item = UserAsset(provider=request.provider.strip())
            session.add(item)
        item.api_key_status = request.api_key_status
        item.balance = request.balance
        item.currency = request.currency
        item.plan = request.plan
        item.available_models = request.available_models
        item.has_account = request.has_account if request.has_account is not None else request.api_key_status == "active"
        item.credit_exchange_rate = request.credit_exchange_rate
        item.subscription = request.subscription
        item.primary_or_backup = request.primary_or_backup
        item.notes = request.notes
        item.enabled = request.enabled
        session.commit()
        prioritize_assets(session)
        return asset_payload(item)

    @app.delete("/assets/{asset_id}")
    def delete_asset(asset_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
        item = session.get(UserAsset, asset_id)
        if item is None:
            raise HTTPException(status_code=404, detail="asset not found")
        session.delete(item)
        session.commit()
        return {"deleted": True}

    @app.get("/local-models")
    def local_models(session: Session = Depends(get_session)) -> list[dict[str, object]]:
        return [{"id": item.id, "model": item.model, "quant": item.quant, "context": item.context,
                 "runtime": item.runtime, "loaded": item.loaded, "benchmark": item.benchmark,
                 "tokens_per_second": str(item.tokens_per_second) if item.tokens_per_second is not None else None,
                 "memory_usage": str(item.memory_usage) if item.memory_usage is not None else None,
                 "updated_at": item.updated_at}
                for item in session.scalars(select(LocalModelRegistry).order_by(LocalModelRegistry.updated_at.desc())).all()]

    @app.post("/local-models")
    def add_local_model(request: LocalModelRequest, session: Session = Depends(get_session)) -> dict[str, object]:
        item = session.scalar(select(LocalModelRegistry).where(LocalModelRegistry.runtime == request.runtime,
                                                               LocalModelRegistry.model == request.model.strip()))
        if item is None:
            item = LocalModelRegistry(runtime=request.runtime, model=request.model.strip())
            session.add(item)
        item.quant = request.quant
        item.context = request.context
        item.loaded = request.loaded
        item.benchmark = request.benchmark
        item.tokens_per_second = request.tokens_per_second
        item.memory_usage = request.memory_usage
        session.commit()
        return {"id": item.id, "model": item.model, "runtime": item.runtime, "loaded": item.loaded}

    @app.get("/scans")
    def scans(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)) -> list[dict[str, object]]:
        return [{"id": r.id, "status": r.status, "triggered_by": r.triggered_by,
                 "started_at": r.started_at, "completed_at": r.completed_at, "error": r.error}
                for r in session.scalars(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(limit)).all()]

    @app.post("/scans")
    def start_scan(background_tasks: BackgroundTasks, provider: str = "all") -> dict[str, object]:
        provider_ids = [item.metadata.provider_id for item in registry.all()] if provider == "all" else [provider]
        unknown = [item for item in provider_ids if item not in {entry.metadata.provider_id for entry in registry.all()}]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown provider: {unknown[0]}")
        background_tasks.add_task(run_scan_job, provider_ids)
        return {"status": "accepted", "providers": provider_ids}

    @app.get("/promotions")
    def promotions(limit: int = Query(50, ge=1, le=500), session: Session = Depends(get_session)) -> list[dict[str, object]]:
        return [{"id": item.id, "provider_id": item.provider_id, "title": item.title,
                 "description": item.description, "promotion_type": item.promotion_type,
                 "start_time": item.start_time, "end_time": item.end_time, "source": item.source,
                 "confidence": str(item.confidence), "captured_at": item.captured_at}
                for item in session.scalars(select(Promotion).order_by(Promotion.captured_at.desc()).limit(limit)).all()]

    @app.post("/promotions")
    def add_promotion(request: PromotionRequest, session: Session = Depends(get_session)) -> dict[str, object]:
        if request.provider_id is not None and session.get(Provider, request.provider_id) is None:
            raise HTTPException(status_code=404, detail="provider not found")
        item = Promotion(provider_id=request.provider_id, title=request.title,
                         description=request.description, promotion_type=request.promotion_type,
                         source=request.source, confidence=request.confidence)
        session.add(item)
        session.commit()
        return {"id": item.id, "title": item.title, "source": item.source, "confidence": str(item.confidence)}

    @app.get("/sources")
    def sources(limit: int = Query(50, ge=1, le=500), session: Session = Depends(get_session)) -> list[dict[str, object]]:
        return [{"source_type": item.source_type, "url": item.url, "title": item.title,
                 "captured_at": item.captured_at, "fetch_success": item.fetch_success, "error": item.error}
                for item in session.scalars(select(Source).order_by(Source.captured_at.desc()).limit(limit)).all()]

    @app.get("/insights")
    def insights(limit: int = Query(30, ge=1, le=200), session: Session = Depends(get_session)) -> list[dict[str, object]]:
        backfill_insights(session)
        rows = session.execute(
            select(IntelligenceInsight, Source, SourceSnapshot)
            .join(SourceSnapshot, SourceSnapshot.id == IntelligenceInsight.source_snapshot_id)
            .join(Source, Source.id == SourceSnapshot.source_id)
            .order_by(IntelligenceInsight.created_at.desc())
            .limit(limit)
        ).all()
        return [{"id": insight.id, "title": source.title, "source_type": source.source_type,
                 "url": source.url, "summary": insight.summary, "impact_level": insight.impact_level,
                 "action": insight.action, "captured_at": snapshot.captured_at,
                 "generated_by": insight.generated_by} for insight, source, snapshot in rows]

    @app.post("/intelligence/scans")
    def start_intelligence_scan(background_tasks: BackgroundTasks) -> dict[str, str]:
        background_tasks.add_task(run_intelligence_job)
        return {"status": "accepted"}

    return app


app = create_app()
