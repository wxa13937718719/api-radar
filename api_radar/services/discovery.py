"""Provider discovery and market coverage bookkeeping.

Discovery is deliberately useful even when a provider has no parser yet: a
candidate is registered with an explicit status instead of disappearing from
the comparison universe.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Provider, ProviderDiscovery, UserAsset


def utc_now() -> datetime:
    return datetime.now(UTC)


KNOWN_CANDIDATES = (
    ("packy", "Packy", "https://packyapi.com", None, "community/search"),
    ("modelflare", "ModelFlare", "https://modelflare.ai", None, "community/search"),
    ("subrouter", "SubRouter", "https://subrouter.ai", None, "community/search"),
    ("vercel", "Vercel AI", "https://vercel.com", "https://vercel.com/ai", "official"),
    ("qiniu", "七牛云", "https://www.qiniu.com", None, "official"),
    ("aihubmix", "AIHubMix", "https://aihubmix.com", None, "community/search"),
    ("cherryin", "CherryIn", "https://cherryin.ai", None, "community/search"),
    ("ocoolai", "ocoolAI", "https://ocoolai.com", None, "community/search"),
    ("poyo", "PoYo", "https://poyo.ai", None, "community/search"),
    ("apimodels", "APIMODELS", "https://apimodels.org", None, "community/search"),
)


def _upsert(session: Session, provider_id: str, display_name: str, homepage: str,
            pricing_source: str | None, source: str, *, priority: int = 0) -> Provider:
    item = session.scalar(select(Provider).where(Provider.provider_id == provider_id))
    if item is None:
        item = Provider(provider_id=provider_id, display_name=display_name, homepage=homepage,
                        pricing_source=pricing_source, adapter_name="GenericWebProviderAdapter",
                        official_url=homepage, pricing_url=pricing_source, discovery_source=source,
                        discovered_at=utc_now(), status="discovered", parser_status="needs_parser",
                        data_confidence=Decimal("0.2"), priority_score=priority)
        session.add(item)
    else:
        item.official_url = item.official_url or homepage
        item.pricing_url = item.pricing_url or pricing_source
        item.discovery_source = item.discovery_source or source
        item.priority_score = max(item.priority_score or 0, priority)
    return item


def seed_known_candidates(session: Session) -> int:
    """Register known market candidates without asserting any prices."""
    count = 0
    for provider_id, name, homepage, pricing, source in KNOWN_CANDIDATES:
        if session.scalar(select(Provider).where(Provider.provider_id == provider_id)) is None:
            _upsert(session, provider_id, name, homepage, pricing, source)
            count += 1
    session.commit()
    return count


def prioritize_assets(session: Session) -> int:
    assets = session.scalars(select(UserAsset).where(UserAsset.enabled.is_(True))).all()
    changed = 0
    for asset in assets:
        provider_id = asset.provider.strip().casefold().replace(" ", "")
        item = session.scalar(select(Provider).where(Provider.provider_id == provider_id))
        if item is None:
            item = _upsert(session, provider_id, asset.provider, "", None, "user_asset", priority=100)
        if item.priority_score != 100 or item.discovery_source != "user_asset":
            item.priority_score = 100
            item.discovery_source = "user_asset"
            changed += 1
    if changed or assets:
        session.commit()
    return changed


def market_coverage(session: Session) -> dict[str, object]:
    providers = session.scalars(select(Provider).where(Provider.ignored.is_(False))).all()
    supported = [p for p in providers if p.status in {"supported", "partially_supported"}]
    comparable = [p for p in supported if p.status == "supported" and p.has_pricing_page]
    pending = [p for p in providers if p.status in {"discovered", "needs_parser", "login_required", "blocked"}]
    assets = session.scalars(select(UserAsset).where(UserAsset.enabled.is_(True))).all()
    ratio = (len(comparable) / len(providers)) if providers else 0
    confidence = "high" if ratio >= 0.6 and len(pending) <= 2 else "medium" if ratio >= 0.35 else "low"
    return {
        "discovered_providers": len(providers),
        "structured_providers": len(supported),
        "comparable_providers": len(comparable),
        "uncovered_candidates": len(pending),
        "configured_providers": len(assets),
        "recommendation_confidence": confidence,
        "coverage_ratio": round(ratio, 3),
        "uncovered": [{"provider_id": p.provider_id, "name": p.display_name, "status": p.status,
                       "reason": p.parser_status, "source": p.discovery_source,
                       "official_url": p.official_url} for p in pending],
    }


def provider_payload(item: Provider) -> dict[str, object]:
    return {"id": item.id, "provider_id": item.provider_id, "display_name": item.display_name,
            "official_url": item.official_url or item.homepage, "pricing_url": item.pricing_url or item.pricing_source,
            "api_base_url": item.api_base_url, "provider_type": item.provider_type,
            "country_or_region": item.country_or_region, "discovery_source": item.discovery_source,
            "discovered_at": item.discovered_at, "last_checked_at": item.last_checked_at,
            "status": item.status, "parser_status": item.parser_status,
            "has_pricing_page": item.has_pricing_page, "has_model_api": item.has_model_api,
            "login_required": item.login_required, "data_confidence": str(item.data_confidence),
            "priority_score": item.priority_score, "ignored": item.ignored}


def record_discovery(session: Session, provider: Provider, *, source_url: str,
                     source_type: str = "search", query: str | None = None,
                     evidence: str | None = None) -> ProviderDiscovery:
    existing = session.scalar(select(ProviderDiscovery).where(
        ProviderDiscovery.provider_id == provider.id, ProviderDiscovery.source_url == source_url
    ))
    if existing is None:
        existing = ProviderDiscovery(provider_id=provider.id, source_url=source_url,
                                     source_type=source_type, query=query, evidence=evidence)
        session.add(existing)
    return existing
