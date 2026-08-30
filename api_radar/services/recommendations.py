"""Evidence-aware two-stage model and provider recommendation engine.

Canonical model quality is kept separate from a provider offer. A cheap offer
can win the second stage, but it can never raise the first-stage capability
score.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..models import (
    LocalModelRegistry,
    Model,
    ModelPrice,
    ModelQualityProfile,
    PriceSnapshot,
    Provider,
    ProviderModel,
    ProviderOffer,
    Recommendation,
    UserAsset,
    UserPreference,
)
from .discovery import market_coverage, prioritize_assets, seed_known_candidates
from .validation import eligible, identity_status, validate_price

PROFILES = ("daily_chat", "coding", "writing", "long_context", "reasoning", "vision", "local_offline", "low_cost", "agent")
TASKS = (("coding", "编程开发"), ("writing", "中文写作"), ("long_context", "长文本分析"),
         ("reasoning", "数学推理"), ("vision", "图片理解"), ("daily_chat", "日常聊天"), ("local_offline", "本地离线任务"))
RECOMMENDATION_MODES = ("best_quality", "balanced", "budget", "free", "my_assets")
MODE_LABELS = {"best_quality": "最强", "balanced": "均衡", "budget": "省钱", "free": "免费", "my_assets": "我的资源"}
CAPABILITY_FOR_PROFILE = {"coding": "coding", "writing": "writing", "long_context": "long_context",
                          "reasoning": "reasoning", "vision": "vision", "daily_chat": "instruction_following",
                          "low_cost": "instruction_following", "agent": "agent_tool_use"}
TASK_COST_TOKENS = {"daily_chat": (20_000, 5_000), "coding": (120_000, 30_000), "writing": (40_000, 20_000),
                    "long_context": (500_000, 60_000), "reasoning": (80_000, 20_000), "vision": (30_000, 10_000),
                    "agent": (100_000, 30_000), "low_cost": (20_000, 5_000)}
CONFIDENCE_VALUE = {"high": Decimal(1), "medium": Decimal("0.7"), "low": Decimal("0.3")}


@dataclass(frozen=True)
class Candidate:
    model: Model
    provider_model: ProviderModel
    provider: Provider
    price: ModelPrice
    offer: ProviderOffer | None
    asset: UserAsset | None


@dataclass(frozen=True)
class QualityEvidence:
    score: Decimal | None
    confidence: str
    source: str | None


def get_user_preference(session: Session) -> UserPreference:
    preference = session.get(UserPreference, 1)
    if preference is None:
        preference = UserPreference(id=1)
        session.add(preference)
        session.commit()
    return preference


def sync_price_board(session: Session) -> None:
    """Backfill the query-friendly price board from immutable snapshots."""
    latest: dict[int, PriceSnapshot] = {}
    for snapshot in session.scalars(select(PriceSnapshot).order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc())).all():
        latest.setdefault(snapshot.provider_model_id, snapshot)
    changed = False
    for provider_model_id, snapshot in latest.items():
        model = session.get(ProviderModel, provider_model_id)
        provider = session.get(Provider, snapshot.provider_id)
        if model is None or provider is None:
            continue
        row = session.scalar(select(ModelPrice).where(ModelPrice.provider == provider.provider_id, ModelPrice.model == model.provider_model_id))
        if row is None:
            row = ModelPrice(provider=provider.provider_id, model=model.provider_model_id)
            session.add(row)
        row.canonical_model_id = model.canonical_model_id
        row.input_price = snapshot.input_price
        row.output_price = snapshot.output_price
        row.context_length = model.context_length
        row.currency = snapshot.currency
        row.source_url = snapshot.source_url or provider.pricing_source
        row.source_type = "provider_api"
        row.updated_time = snapshot.captured_at
        validation, _, reason = validate_price(snapshot.input_price, unit=f"{snapshot.currency}/1M_tokens", field="input_price")
        row.validation_status = "partial" if validation == "verified" and snapshot.output_price is None else validation
        row.identity_status = identity_status(model.provider_model_id)
        row.confidence = snapshot.confidence or Decimal(1)
        row.invalid_reason = reason or snapshot.invalid_reason
        changed = True
    if changed:
        session.commit()


def _asset_key(value: str) -> str:
    return value.casefold().replace(" ", "").replace("-", "").replace("_", "")


def _asset_usable(asset: UserAsset | None) -> bool:
    if asset is None or not asset.enabled:
        return False
    return bool(asset.has_account or asset.api_key_status == "active" or asset.balance is not None or asset.plan or asset.subscription)


def _candidate_rows(session: Session) -> list[Candidate]:
    seed_known_candidates(session)
    prioritize_assets(session)
    sync_price_board(session)
    assets = {_asset_key(asset.provider): asset for asset in session.scalars(select(UserAsset).where(UserAsset.enabled.is_(True))).all()}
    statement = select(ModelPrice, ProviderModel, Provider, Model).join(Provider, Provider.provider_id == ModelPrice.provider).join(
        ProviderModel, and_(ProviderModel.provider_id == Provider.id, ProviderModel.provider_model_id == ModelPrice.model)
    ).join(Model, Model.canonical_model_id == ModelPrice.canonical_model_id).where(ModelPrice.canonical_model_id.is_not(None))
    rows: list[Candidate] = []
    for price, provider_model, provider, canonical in session.execute(statement).all():
        if not eligible(validation=price.validation_status or "verified", identity=price.identity_status or "verified",
                        provider_status=provider.status, input_price=price.input_price):
            continue
        offer = session.scalar(select(ProviderOffer).where(ProviderOffer.provider_id == provider.id,
            ProviderOffer.canonical_model_id == canonical.canonical_model_id,
            ProviderOffer.provider_model_id == provider_model.provider_model_id))
        rows.append(Candidate(canonical, provider_model, provider, price, offer, assets.get(_asset_key(provider.provider_id))))
    return rows


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _quality(session: Session, candidate: Candidate, capability: str) -> QualityEvidence:
    row = session.scalar(select(ModelQualityProfile).where(ModelQualityProfile.canonical_model_id == candidate.model.canonical_model_id,
                                                            ModelQualityProfile.capability == capability))
    if row is not None and row.score is not None:
        return QualityEvidence(_decimal(row.score), row.confidence or "low", row.source)
    quality = (candidate.model.capabilities or {}).get("quality_profiles", {})
    value = quality.get(capability) if isinstance(quality, dict) else None
    if isinstance(value, dict) and value.get("score") is not None:
        return QualityEvidence(_decimal(value["score"]), str(value.get("confidence") or "low"), str(value.get("source") or "model_metadata"))
    return QualityEvidence(None, "low", None)


def _offer_mode(candidate: Candidate) -> str:
    explicit = (candidate.offer.interaction_mode if candidate.offer else None) or "realtime"
    if explicit != "realtime":
        return explicit
    # Older snapshots predate interaction_mode.  Batch is part of the
    # provider-model identity on several catalogs (for example `:batch`), so
    # classify that explicit suffix instead of silently treating it as chat API.
    identity = f"{candidate.provider_model.provider_model_id} {candidate.provider_model.provider_model_name}".casefold()
    if "batch" in identity:
        return "batch"
    if "subscription" in identity:
        return "subscription"
    return "realtime"


def _is_free(candidate: Candidate) -> bool:
    # An unknown output price is not evidence of a free model.
    return candidate.price.input_price == 0 and candidate.price.output_price == 0


def _profile_candidate_allowed(candidate: Candidate, profile: str) -> bool:
    """Reject candidates that have explicit contradictory capability metadata."""
    if profile != "vision":
        return True
    metadata = candidate.provider_model.capabilities or candidate.model.capabilities or {}
    modalities = metadata.get("input_modalities")
    if not isinstance(modalities, list) or not modalities:
        # Missing evidence is handled as low confidence, not as a guessed
        # capability.  Keep the candidate visible so the UI can say that data
        # is insufficient rather than silently claiming no model exists.
        return True
    return any(str(item).casefold() in {"image", "image_url", "video", "multimodal"} for item in modalities)


def _supports_agent(candidate: Candidate) -> bool:
    params = (candidate.model.capabilities or {}).get("supported_parameters", [])
    compatibility = _decimal(candidate.offer.compatibility_score) if candidate.offer else None
    return ("tools" in params or "tool_choice" in params) and (compatibility is None or compatibility >= 60)


def _offer_score(candidate: Candidate, field: str) -> tuple[Decimal, bool]:
    value = _decimal(getattr(candidate.offer, field, None)) if candidate.offer else None
    return (max(Decimal(0), min(Decimal(100), value)), True) if value is not None else (Decimal(50), False)


def _stability_score(candidate: Candidate) -> tuple[Decimal, bool]:
    score, reliable = _offer_score(candidate, "stability_score")
    risk = (candidate.offer.channel_risk if candidate.offer else "unknown") or "unknown"
    # Channel risk is offer evidence, not model ability.  It caps the channel
    # stability contribution without inventing a new model-quality score.
    cap = {"critical": Decimal(20), "high": Decimal(40), "medium": Decimal(65)}.get(risk.casefold())
    return (min(score, cap), reliable) if cap is not None else (score, reliable)


def _estimated_cost(candidate: Candidate, profile: str) -> tuple[Decimal | None, str | None]:
    input_tokens, output_tokens = TASK_COST_TOKENS.get(profile, TASK_COST_TOKENS["daily_chat"])
    if candidate.price.input_price is None or candidate.price.output_price is None:
        return None, candidate.price.currency
    return ((Decimal(input_tokens) * candidate.price.input_price + Decimal(output_tokens) * candidate.price.output_price) / Decimal(1_000_000), candidate.price.currency)


def _price_score(candidates: list[Candidate], profile: str, *, paid_only: bool = False) -> dict[int, tuple[Decimal, bool]]:
    costs: list[tuple[int, Decimal]] = []
    for candidate in candidates:
        if paid_only and _is_free(candidate):
            continue
        cost, _ = _estimated_cost(candidate, profile)
        if cost is not None:
            costs.append((id(candidate), cost))
    result = {id(candidate): (Decimal(50), False) for candidate in candidates}
    if not costs:
        return result
    minimum, maximum = min(value for _, value in costs), max(value for _, value in costs)
    for identity, value in costs:
        score = Decimal(100) if minimum == maximum else Decimal(20) + (maximum - value) / (maximum - minimum) * Decimal(80)
        result[identity] = (score, True)
    return result


def _asset_matches(asset: UserAsset | None, candidate: Candidate) -> bool:
    if not _asset_usable(asset):
        return False
    models = [str(item).casefold() for item in (asset.available_models or [])]
    if not models:
        return True
    needles = {candidate.model.canonical_model_id.casefold(), candidate.provider_model.provider_model_id.casefold(), candidate.model.display_name.casefold()}
    return any(any(needle in item or item in needle for needle in needles) for item in models)


def _asset_priority(asset: UserAsset | None) -> Decimal:
    if not _asset_usable(asset):
        return Decimal(0)
    score = Decimal(35)
    if asset.api_key_status == "active" or asset.has_account:
        score += 20
    if asset.balance is not None and asset.balance > 0:
        score += 25
    if asset.plan or asset.subscription:
        score += 15
    return score + (Decimal(5) if asset.primary_or_backup == "primary" else Decimal(0))


def _mode_allowed(candidate: Candidate, profile: str, mode: str) -> bool:
    interaction = _offer_mode(candidate)
    if interaction in {"batch", "subscription"} or profile == "local_offline":
        return False
    if mode == "free" and not _is_free(candidate):
        return False
    if mode == "budget" and _is_free(candidate):
        return False
    if mode == "budget" and _estimated_cost(candidate, profile)[0] is None:
        # A budget ranking requires both input and output prices; never infer a
        # typical cost from an input-only or otherwise incomplete quote.
        return False
    if mode == "my_assets" and not _asset_matches(candidate.asset, candidate):
        return False
    return not (profile == "agent" and (interaction not in {"realtime", "agent"} or not _supports_agent(candidate)))


def _reason(candidate: Candidate, profile: str, mode: str, quality: QualityEvidence, cost: Decimal | None,
            stability: Decimal, coverage: dict[str, object]) -> str:
    label = dict(TASKS).get(profile, "当前任务")
    parts = [f"{label}能力数据不足（{quality.confidence.title()} Confidence）" if quality.score is None else f"{label}能力证据 {quality.score:.0f}（来源：{quality.source or '未标注'}）"]
    if cost is not None:
        parts.append(f"按典型调用量预计 {cost:.4f} {candidate.price.currency}")
    if _asset_matches(candidate.asset, candidate):
        parts.append(f"你已有 {candidate.asset.provider} 资源，无需另行注册")
    parts.append("渠道稳定性暂无可靠证据" if stability == 50 else f"渠道稳定性证据 {stability:.0f}")
    if coverage.get("comparable_providers", 0) < 3:
        parts.append("当前已验证渠道中，覆盖不足，不能代表全网最低价")
    if mode == "free":
        parts.append("免费与付费榜单分离")
    return "；".join(parts) + "。"


def _local_results(session: Session, profile: str, limit: int, coverage: dict[str, object]) -> list[dict[str, object]]:
    if profile != "local_offline":
        return []
    records = session.scalars(select(LocalModelRegistry).where(LocalModelRegistry.loaded.is_(True)).order_by(LocalModelRegistry.updated_at.desc())).all()
    result: list[dict[str, object]] = []
    for record in records:
        model = session.get(Model, record.model)
        display_name = model.display_name if model else record.model
        canonical_id = model.canonical_model_id if model else record.model
        quality = _quality(session, Candidate(model, ProviderModel(provider_model_id=record.model, provider_model_name=display_name),
                              Provider(provider_id=record.runtime, display_name="LM Studio", adapter_name="local"),
                              ModelPrice(provider=record.runtime, model=record.model, currency="LOCAL"), None, None), "instruction_following") if model else QualityEvidence(None, "low", None)
        score = int(quality.score) if quality.score is not None else None
        result.append({"model": display_name, "canonical_model_id": canonical_id, "provider": "LM Studio", "provider_id": record.runtime,
                       "input_price": None, "output_price": None, "currency": "LOCAL", "context_length": record.context,
                       "speed_score": str(record.tokens_per_second or "数据不足"), "ability_score": str(score) if score is not None else "数据不足",
                       "stability_score": "数据不足", "value_score": str(score) if score is not None else "数据不足", "score": score,
                       "score_confidence": quality.confidence, "data_confidence": quality.confidence, "coverage": coverage,
                       "why": "已在本机 LM Studio 标记为 loaded；云端 Provider 不参与本地离线推荐。", "reason": "已在本机 LM Studio 标记为 loaded；云端 Provider 不参与本地离线推荐。",
                       "asset_available": False, "interaction_mode": "local", "eligibility": "eligible", "estimated_cost": None,
                       "estimated_cost_currency": "LOCAL", "source_url": None, "updated_time": record.updated_at})
    return result[:limit]


def decision_recommendations(session: Session, *, profile: str, mode: str = "balanced", limit: int = 5) -> list[dict[str, object]]:
    if profile not in PROFILES:
        raise ValueError(f"Unknown recommendation profile: {profile}")
    if mode not in RECOMMENDATION_MODES:
        raise ValueError(f"Unknown recommendation mode: {mode}")
    # Coverage is part of the recommendation evidence. Seed discovery candidates
    # before taking the snapshot so a result cannot claim broad market coverage
    # merely because discovery bookkeeping happened later in the query path.
    seed_known_candidates(session)
    prioritize_assets(session)
    coverage = market_coverage(session)
    local = _local_results(session, profile, limit, coverage)
    if local:
        return local
    candidates = _candidate_rows(session)
    if not candidates:
        return []
    capability = CAPABILITY_FOR_PROFILE.get(profile, "instruction_following")
    quality = {candidate.model.canonical_model_id: _quality(session, candidate, capability) for candidate in candidates}
    allowed = [candidate for candidate in candidates
               if _profile_candidate_allowed(candidate, profile) and _mode_allowed(candidate, profile, mode)]
    if not allowed:
        return []
    price_scores = _price_score(allowed, profile, paid_only=mode in {"balanced", "budget", "best_quality", "my_assets"})
    grouped: dict[str, list[Candidate]] = {}
    for candidate in allowed:
        grouped.setdefault(candidate.model.canonical_model_id, []).append(candidate)
    results: list[dict[str, object]] = []
    for canonical_id, offers in grouped.items():
        evidence = quality[canonical_id]
        def offer_key(item: Candidate) -> tuple[Decimal, Decimal, Decimal]:
            price = price_scores[id(item)][0]
            stability = _stability_score(item)[0]
            speed = _offer_score(item, "speed_score")[0]
            asset = _asset_priority(item.asset) if mode == "my_assets" else Decimal(0)
            if mode == "best_quality":
                return (stability, speed, price)
            if mode == "free":
                return (stability, speed, price)
            if mode == "my_assets":
                return (asset, stability, price)
            return (price, stability, speed)
        selected = max(offers, key=offer_key)
        price_score, price_reliable = price_scores[id(selected)]
        speed, speed_reliable = _offer_score(selected, "speed_score")
        stability, stability_reliable = _stability_score(selected)
        compatibility, _compatibility_reliable = _offer_score(selected, "compatibility_score")
        cost, cost_currency = _estimated_cost(selected, profile)
        quality_numeric = evidence.score if evidence.score is not None else Decimal(50)
        asset_score = _asset_priority(selected.asset)
        if mode == "best_quality":
            numeric = quality_numeric * Decimal("0.70") + speed * Decimal("0.10") + stability * Decimal("0.10") + compatibility * Decimal("0.10")
        elif mode == "budget":
            numeric = quality_numeric * Decimal("0.20") + price_score * Decimal("0.60") + speed * Decimal("0.10") + stability * Decimal("0.10")
        elif mode == "free":
            numeric = quality_numeric * Decimal("0.55") + speed * Decimal("0.20") + stability * Decimal("0.15") + compatibility * Decimal("0.10")
        elif mode == "my_assets":
            numeric = quality_numeric * Decimal("0.35") + price_score * Decimal("0.25") + speed * Decimal("0.10") + stability * Decimal("0.10") + asset_score * Decimal("0.20")
        else:
            numeric = quality_numeric * Decimal("0.40") + price_score * Decimal("0.30") + speed * Decimal("0.15") + stability * Decimal("0.15")
        confidence_value = min(CONFIDENCE_VALUE.get(evidence.confidence, Decimal("0.3")), Decimal(str(selected.price.confidence or "0.5")),
                               Decimal(1) if price_reliable else Decimal("0.3"), Decimal(1) if (speed_reliable and stability_reliable) else Decimal("0.3"))
        confidence = "high" if confidence_value >= Decimal("0.8") else "medium" if confidence_value >= Decimal("0.6") else "low"
        display_score = str(int(numeric.quantize(Decimal(1)))) if confidence != "low" else "数据不足"
        reason = _reason(selected, profile, mode, evidence, cost, stability if stability_reliable else Decimal(50), coverage)
        results.append({"model": selected.provider_model.provider_model_name, "canonical_model_id": canonical_id,
                        "provider": selected.provider.display_name, "provider_id": selected.provider.provider_id,
                        "input_price": str(selected.price.input_price) if selected.price.input_price is not None else None,
                        "output_price": str(selected.price.output_price) if selected.price.output_price is not None else None,
                        "currency": selected.price.currency, "context_length": selected.price.context_length,
                        "speed_score": str(int(speed)) if speed_reliable else "数据不足", "ability_score": str(int(evidence.score)) if evidence.score is not None else "数据不足",
                        "stability_score": str(int(stability)) if stability_reliable else "数据不足", "value_score": display_score,
                        "score": int(numeric.quantize(Decimal(1))) if confidence != "low" else None,
                        "dimensions": {"ability": str(int(evidence.score)) if evidence.score is not None else "数据不足", "price": str(int(price_score)) if price_reliable else "数据不足",
                                       "speed": str(int(speed)) if speed_reliable else "数据不足", "stability": str(int(stability)) if stability_reliable else "数据不足"},
                        "asset_available": _asset_matches(selected.asset, selected), "asset_reason": f"已有 {selected.asset.provider} 资源" if _asset_matches(selected.asset, selected) else None,
                        "data_confidence": confidence, "score_confidence": confidence, "coverage": coverage, "interaction_mode": _offer_mode(selected),
                        "is_free": _is_free(selected), "estimated_cost": str(cost) if cost is not None else None, "estimated_cost_currency": cost_currency,
                        "eligibility": "eligible", "why": reason, "reason": reason, "source_url": selected.price.source_url, "updated_time": selected.price.updated_time})
        # Keep ranking precision internal when evidence is low.  It lets the
        # mode-specific ordering remain meaningful without displaying a fake
        # 92.5-style score to the user.
        results[-1]["_sort_score"] = numeric
    ordered = sorted(results, key=lambda item: (item["_sort_score"], item["asset_available"], item["model"]), reverse=True)[:limit]
    for item in ordered:
        item.pop("_sort_score", None)
    return ordered


def generate_recommendations(session: Session, *, profile: str, mode: str = "balanced", limit: int = 5) -> list[Recommendation]:
    rows = decision_recommendations(session, profile=profile, mode=mode, limit=limit)
    results = [Recommendation(profile=f"{profile}:{mode}", provider_id=session.scalar(select(Provider.id).where(Provider.provider_id == row["provider_id"])),
                              canonical_model_id=str(row["canonical_model_id"]) if row["canonical_model_id"] else None,
                              total_score=Decimal(str(row.get("score") or "0")), dimension_scores=row["dimensions"], reason=str(row["reason"])) for row in rows]
    session.add_all(results)
    session.commit()
    return results


def daily_decision_center(session: Session) -> dict[str, object]:
    recommendations = []
    for task_id, label in TASKS:
        modes = {mode: decision_recommendations(session, profile=task_id, mode=mode, limit=5) for mode in RECOMMENDATION_MODES}
        recommendations.append({"task_id": task_id, "task": label, "recommendations": modes["balanced"], "modes": modes, "mode_labels": MODE_LABELS})
    assets = session.scalars(select(UserAsset).order_by(UserAsset.provider)).all()
    coding = recommendations[0]["recommendations"]
    actions: list[str] = []
    if coding:
        first = coding[0]
        actions.append(f"编程开发先用 {first['provider']} 的 {first['model']}（{first['value_score']}）。")
    configured = [asset.provider for asset in assets if _asset_usable(asset)]
    if configured:
        actions.append("优先消化现有账号：" + "、".join(configured) + " 已配置可用资源。")
    actions.append("购买前先对照输入+输出典型成本、套餐限制与实际调用量；订阅和 batch 不默认当作实时 API。")
    coverage = market_coverage(session)
    if coverage["recommendation_confidence"] != "high":
        actions.insert(0, f"当前仅基于 {coverage['comparable_providers']} 个已验证渠道；尚未纳入：" + "、".join(item["name"] for item in coverage["uncovered"][:8]) + "。")
    return {"score_formula": "先选模型能力，再选 Provider 报价；能力 40% + 价格 30% + 速度 15% + 稳定性 15%（模式会调整排序）。", "recommendation_confidence": coverage["recommendation_confidence"], "coverage": coverage, "recommendations": recommendations, "actions": actions}
