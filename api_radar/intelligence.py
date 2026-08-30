"""Public intelligence collection kept separate from provider adapters."""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import IntelligenceInsight, Provider, Source, SourceSnapshot, utc_now

MAX_SAFE_TEXT = 20000


def _insight_for(spec: OfficialSourceSpec, status: str, safe_text: str) -> tuple[str, str, str]:
    """Turn evidence into a compact UI-safe summary, impact and action."""
    normalized = " ".join(safe_text.split())
    excerpt = normalized[:360].rstrip("。；，") if normalized else "页面没有提取到可显示的正文。"
    urgent_terms = ("停止服务", "终止", "失效", "到期", "禁止", "涨价", "下线", "删除")
    if any(term in normalized for term in urgent_terms):
        impact = "critical"
        action = "立即打开官方页面核对限制或价格，并暂停受影响的自动化任务。"
    elif status == "changed" and spec.source_type in {"pricing", "provider_pricing", "promotion", "free_quota"}:
        impact = "high"
        action = "今天重新比较价格和资格条件；确认后再调整默认模型或套餐。"
    elif status == "initial":
        impact = "medium"
        action = "这是首次建立监测基线，不等于今天发布；先加入观察列表。"
    elif status == "changed":
        impact = "medium"
        action = "建议查看来源摘要，确认是否影响你的使用场景。"
    else:
        impact = "low"
        action = "当前没有需要立即处理的变化，保持每日监测即可。"
    status_text = {"initial": "首次纳入监测", "changed": "检测到页面变化", "unchanged": "页面内容未变化"}.get(status, status)
    summary = f"{status_text}：{excerpt}。"
    return summary, impact, action


def backfill_insights(session: Session) -> int:
    """Create summaries for snapshots captured before the insight table existed."""
    rows = session.execute(
        select(SourceSnapshot, Source).join(Source, Source.id == SourceSnapshot.source_id)
    ).all()
    created = 0
    for snapshot, source in rows:
        exists = session.scalar(select(IntelligenceInsight.id).where(
            IntelligenceInsight.source_snapshot_id == snapshot.id
        ))
        if exists is not None or not snapshot.fetch_success:
            continue
        previous = session.scalar(select(SourceSnapshot.id).where(
            SourceSnapshot.source_id == source.id,
            SourceSnapshot.id != snapshot.id,
            SourceSnapshot.fetch_success.is_(True),
            SourceSnapshot.captured_at < snapshot.captured_at,
        ).limit(1))
        status = "changed" if snapshot.changed_since_previous else "initial" if previous is None else "unchanged"
        spec = OfficialSourceSpec(source.source_type, source.url, source.title or source.url)
        summary, impact, action = _insight_for(spec, status, snapshot.safe_text or "")
        session.add(IntelligenceInsight(source_snapshot_id=snapshot.id, summary=summary,
                                        impact_level=impact, action=action, generated_by="rules"))
        created += 1
    if created:
        session.commit()
    return created


@dataclass(frozen=True)
class OfficialSourceSpec:
    source_type: str
    url: str
    title: str


OFFICIAL_SOURCES = (
    OfficialSourceSpec("promotion", "https://help.aliyun.com/zh/model-studio/coding-plan", "阿里云百炼 Coding Plan"),
    OfficialSourceSpec("free_quota", "https://help.aliyun.com/zh/model-studio/new-free-quota", "阿里云百炼新人免费额度"),
    OfficialSourceSpec("pricing", "https://help.aliyun.com/zh/model-studio/model-pricing", "阿里云百炼模型价格"),
    OfficialSourceSpec("pricing", "https://api-docs.deepseek.com/quick_start/pricing", "DeepSeek API 定价"),
    OfficialSourceSpec("pricing", "https://open.bigmodel.cn/pricing", "智谱 GLM 模型价格"),
    OfficialSourceSpec("pricing", "https://platform.openai.com/docs/pricing", "OpenAI API Pricing"),
    OfficialSourceSpec("pricing", "https://docs.anthropic.com/en/docs/about-claude/pricing", "Anthropic Claude Pricing"),
    OfficialSourceSpec("pricing", "https://ai.google.dev/gemini-api/docs/pricing", "Google Gemini API Pricing"),
    OfficialSourceSpec("pricing", "https://mistral.ai/products/la-plateforme#pricing", "Mistral La Plateforme Pricing"),
    OfficialSourceSpec("pricing", "https://groq.com/pricing", "Groq Pricing"),
    # Community pages are leads only: they never feed prices or the value score
    # unless the linked provider's own pricing page confirms the information.
    OfficialSourceSpec("github", "https://github.com/topics/llm", "GitHub · LLM projects"),
    OfficialSourceSpec("community", "https://linux.do/c/ai/6", "Linux.do · AI"),
    OfficialSourceSpec("reddit", "https://www.reddit.com/r/LocalLLaMA/", "Reddit · r/LocalLLaMA"),
)


@dataclass(frozen=True)
class IntelligenceResult:
    source_url: str
    success: bool
    title: str | None
    change_status: str
    error: str | None = None


def _safe_page_text(response: httpx.Response) -> tuple[str | None, str]:
    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    text = " ".join(soup.get_text(" ", strip=True).split())[:MAX_SAFE_TEXT]
    return title, text


async def collect_official_sources(
    session: Session,
    *,
    source_specs: tuple[OfficialSourceSpec, ...] = OFFICIAL_SOURCES,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[IntelligenceResult]:
    providers = session.scalars(select(Provider).where(Provider.pricing_source.is_not(None))).all()
    combined = list(source_specs)
    combined.extend(
        OfficialSourceSpec("provider_pricing", provider.pricing_source, provider.display_name)
        for provider in providers
        if provider.pricing_source
    )
    specs = list({spec.url: spec for spec in combined}.values())
    client_options: dict[str, object] = {
        "timeout": 30.0,
        "follow_redirects": True,
        "headers": {"User-Agent": "API-Radar/0.1 official-source-monitor"},
    }
    if transport is not None:
        client_options["transport"] = transport

    async with httpx.AsyncClient(**client_options) as client:
        async def fetch(spec: OfficialSourceSpec) -> tuple[OfficialSourceSpec, httpx.Response | None, str | None]:
            try:
                response = await client.get(spec.url)
                response.raise_for_status()
                return spec, response, None
            except httpx.HTTPError as exc:
                return spec, None, repr(exc)

        fetched = await asyncio.gather(*(fetch(spec) for spec in specs))

    results: list[IntelligenceResult] = []
    for spec, response, error in fetched:
        source = session.scalar(select(Source).where(Source.url == spec.url))
        if source is None:
            source = Source(source_type=spec.source_type, url=spec.url, title=spec.title)
            session.add(source)
            session.flush()
        source.source_type = spec.source_type
        source.captured_at = utc_now()
        previous = session.scalar(
            select(SourceSnapshot)
            .where(SourceSnapshot.source_id == source.id, SourceSnapshot.fetch_success.is_(True))
            .order_by(SourceSnapshot.captured_at.desc(), SourceSnapshot.id.desc())
            .limit(1)
        )
        if response is None:
            source.fetch_success = False
            source.error = error
            session.add(SourceSnapshot(source_id=source.id, fetch_success=False, error=error))
            results.append(IntelligenceResult(spec.url, False, source.title, "failed", error))
            continue

        page_title, safe_text = _safe_page_text(response)
        content_hash = hashlib.sha256(safe_text.encode("utf-8")).hexdigest()
        changed = previous is not None and previous.content_hash != content_hash
        status = "changed" if changed else "initial" if previous is None else "unchanged"
        source.title = page_title or spec.title
        source.safe_raw_response = safe_text
        source.fetch_success = True
        source.error = None
        snapshot = SourceSnapshot(
            source_id=source.id,
            content_hash=content_hash,
            safe_text=safe_text,
            fetch_success=True,
            changed_since_previous=changed,
        )
        session.add(snapshot)
        session.flush()
        summary, impact, action = _insight_for(spec, status, safe_text)
        session.add(IntelligenceInsight(
            source_snapshot_id=snapshot.id,
            summary=summary,
            impact_level=impact,
            action=action,
            generated_by="rules",
        ))
        results.append(IntelligenceResult(spec.url, True, source.title, status))

    session.commit()
    return results
