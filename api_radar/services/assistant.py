"""Optional OpenAI-compatible assistant with a deterministic local fallback."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Promotion, Source, SourceSnapshot
from .prices import recent_price_changes
from .recommendations import daily_decision_center, generate_recommendations, get_user_preference

PREFERENCE_KEYWORDS = {
    "budget": ("省钱", "低成本", "便宜", "预算", "价格", "性价比"),
    "quality": ("质量", "准确", "推理", "编程", "代码", "效果"),
    "context": ("长上下文", "上下文", "长文", "文档", "百万 token"),
    "tools": ("工具调用", "函数调用", "agent", "智能体", "openclaw"),
}
INTELLIGENCE_KEYWORDS = (
    "新客", "首月", "优惠", "免费额度", "有效期", "用完即停", "价格", "输入", "输出",
    "缓存", "调用", "每月", "每周", "每天", "限制", "禁止", "模型", "Coding Plan",
)


def _relevant_excerpt(value: str, limit: int = 2400) -> str:
    normalized = " ".join(value.split())
    excerpts: list[str] = []
    for keyword in INTELLIGENCE_KEYWORDS:
        start = normalized.lower().find(keyword.lower())
        if start < 0:
            continue
        excerpt = normalized[max(0, start - 150):start + 420].strip()
        if excerpt and all(excerpt not in existing for existing in excerpts):
            excerpts.append(excerpt)
        if sum(len(item) for item in excerpts) >= limit:
            break
    return " … ".join(excerpts)[:limit] or normalized[:limit]


def _official_opportunity_summary(item: dict[str, Any]) -> str | None:
    text = item["official_excerpt"]
    url = item["url"]
    if "coding-plan" in url:
        promo = re.search(r"首月\s*[¥￥]\s*([0-9.]+).*?目录价\s*[¥￥]\s*([0-9.]+)", text)
        quotas = re.search(r"每\s*5\s*小时\s*([0-9,]+).*?每周\s*([0-9,]+).*?每月\s*([0-9,]+)", text)
        refill = re.search(r"每日\s*(\d{2}:\d{2})", text)
        details = []
        if promo:
            details.append(f"Pro 新客首月 **¥{promo.group(1)}**，目录价 **¥{promo.group(2)}/月**")
        if quotas:
            details.append(f"额度为每 5 小时 {quotas.group(1)} 次、每周 {quotas.group(2)} 次、每月 {quotas.group(3)} 次调用")
        if refill:
            details.append(f"限量名额每日北京时间 {refill.group(1)} 补充")
        models = [name for name in ("Qwen", "GLM", "Kimi", "MiniMax") if name.lower() in text.lower()]
        if models:
            details.append("页面列出的模型包含 " + "、".join(models))
        if details:
            return "；".join(details) + f"。[官方说明]({url})"
    if "new-free-quota" in url:
        details = []
        if "自动为您发放各模型" in text:
            details.append("首次开通后会按模型自动发放新人免费额度")
        token = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万\s*(?:Token|tokens)", text, re.IGNORECASE)
        if token:
            details.append(f"页面列出的单项额度最高包含约 {token.group(1)} 万 Token")
        days = re.search(r"有效期[^。]{0,40}?([0-9]+)\s*天", text)
        if days:
            details.append(f"有效期 {days.group(1)} 天")
        if "用完即停" in text:
            details.append("可以开启“免费额度用完即停”避免意外计费")
        if details:
            return "；".join(details) + f"。[官方说明]({url})"
    return None


def update_preference_from_messages(session: Session, messages: list[dict[str, str]]) -> dict[str, object]:
    """Apply transparent, conservative local preferences from explicit user wording."""
    preference = get_user_preference(session)
    priorities = dict(preference.priorities or {})
    matched: list[str] = []
    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content", "").lower()
        for key, keywords in PREFERENCE_KEYWORDS.items():
            if any(keyword in content for keyword in keywords):
                priorities[key] = 3 if any(word in content for word in ("优先", "最", "尽量", "主要")) else 2
                matched.append(key)
    if matched:
        preference.priorities = priorities
        session.commit()
    return {"priorities": priorities, "updated": sorted(set(matched))}


def _facts(session: Session, profile: str = "daily_chat") -> dict[str, Any]:
    recommendations = generate_recommendations(session, profile=profile, limit=5)
    decision = daily_decision_center(session)
    snapshots = session.scalars(
        select(SourceSnapshot)
        .where(SourceSnapshot.fetch_success.is_(True))
        .order_by(SourceSnapshot.captured_at.desc(), SourceSnapshot.id.desc())
        .limit(40)
    ).all()
    latest_by_source: dict[int, SourceSnapshot] = {}
    for snapshot in snapshots:
        latest_by_source.setdefault(snapshot.source_id, snapshot)
    intelligence = []
    for snapshot in latest_by_source.values():
        source = session.get(Source, snapshot.source_id)
        if source is None:
            continue
        status = "changed" if snapshot.changed_since_previous else "current"
        previous_count = session.scalar(
            select(SourceSnapshot.id)
            .where(SourceSnapshot.source_id == source.id, SourceSnapshot.id != snapshot.id)
            .limit(1)
        )
        if previous_count is None:
            status = "initial"
        intelligence.append({
            "status": status,
            "source_type": source.source_type,
            "title": source.title,
            "url": source.url,
            "captured_at": snapshot.captured_at.isoformat(),
            "official_excerpt": _relevant_excerpt(snapshot.safe_text or ""),
        })
    type_priority = {"promotion": 0, "free_quota": 1, "provider_pricing": 2, "pricing": 3}
    intelligence.sort(key=lambda item: (
        {"changed": 0, "initial": 1, "current": 2}[item["status"]],
        type_priority.get(item["source_type"], 4),
    ))
    promotions = session.scalars(
        select(Promotion).order_by(Promotion.captured_at.desc()).limit(8)
    ).all()
    price_changes = [
        item for item in recent_price_changes(session, 40)
        if item["change_type"] in {"decreased", "increased", "new"}
    ][:16]
    return {
        "profile": profile,
        "daily_decision": decision,
        "recommendations": [{"provider_id": row.provider_id, "canonical_model_id": row.canonical_model_id,
                             "score": str(row.total_score), "reason": row.reason} for row in recommendations],
        "price_changes": price_changes,
        "official_intelligence": intelligence[:12],
        "verified_promotions": [{
            "title": item.title,
            "description": item.description,
            "promotion_type": item.promotion_type,
            "source": item.source,
            "confidence": str(item.confidence),
        } for item in promotions],
    }


def deterministic_briefing_from_facts(facts: dict[str, Any]) -> str:
    rows = facts["recommendations"]
    changes = facts["price_changes"]
    intelligence = facts.get("official_intelligence", [])
    changed = [item for item in intelligence if item["status"] == "changed"]
    initial = [item for item in intelligence if item["status"] == "initial"]
    decreased = sum(1 for item in changes if item["change_type"] == "decreased")
    increased = sum(1 for item in changes if item["change_type"] == "increased")
    paragraphs = []
    actions = facts.get("daily_decision", {}).get("actions", [])
    if actions:
        paragraphs.append("**今天建议**：\n" + "\n".join(
            f"{index}. {action}" for index, action in enumerate(actions[:3], start=1)
        ))
    if changed:
        links = "、".join(f"[{item['title']}]({item['url']})" for item in changed[:4])
        paragraphs.append(f"今天检测到 **{len(changed)} 个官方页面发生内容变化**：{links}。需要结合页面正文确认具体优惠、额度和限制后再行动。")
    elif initial:
        links = "、".join(f"[{item['title']}]({item['url']})" for item in initial[:4])
        paragraphs.append(f"今天首次纳入 **{len(initial)} 个官方情报来源**，包括 {links}。这是监测基线，不代表这些政策都在今天发布。")
    else:
        paragraphs.append("今天已监测的官方情报页面暂未检测到内容变化。")
    current_opportunities = [
        item for item in intelligence
        if item["source_type"] in {"promotion", "free_quota"}
    ]
    for item in (changed or current_opportunities or initial)[:3]:
        status_label = {
            "changed": "检测到页面更新",
            "initial": "首次建立监测基线",
            "current": "当前官方页面仍有效",
        }[item["status"]]
        summary = _official_opportunity_summary(item)
        if summary is None:
            excerpt = item["official_excerpt"][:260].rstrip()
            summary = f"{excerpt}… [查看官方原文]({item['url']})"
        paragraphs.append(f"**{item['title']}**（{status_label}）：{summary}")
    if current_opportunities:
        paragraphs.append("**今天的行动建议**：如果你符合百炼新客条件并且主要在交互式编程工具中高频使用模型，Coding Plan 的首月优惠值得测试；同时开启新人免费额度“用完即停”。订阅套餐和普通 API 的用途不同，接入自动化后端或批量任务前必须核对官方限制。")
    stable_reference_pages = [
        item for item in intelligence
        if item["status"] == "current"
        and ("deepseek" in item["url"].lower() or "bigmodel" in item["url"].lower())
    ]
    if stable_reference_pages:
        references = "、".join(f"[{item['title']}]({item['url']})" for item in stable_reference_pages)
        paragraphs.append(f"DeepSeek / GLM 方面，今天没有检测到官方定价页面内容变化：{references}。这表示页面正文哈希未变，不代表平台运行状态或临时活动绝对没有变化。")
    paragraphs.append(f"价格快照中发现 **{decreased} 个降价、{increased} 个涨价** 项目；它们只代表相邻公开快照差异，需要结合模型版本和计费单位判断实际价值。")
    if not intelligence:
        if rows:
            lead = rows[0]
            paragraphs.append(f"按当前 {facts['profile']} 规则，低成本候选是 **{lead['canonical_model_id'] or '未确认模型'}**。这个排名主要基于公开价格和可用元数据，不等同于质量评测。")
        else:
            paragraphs.append("今天还没有足够的标准化价格快照生成模型候选。")
    return "\n\n".join(paragraphs)


async def _chat_completion(messages: list[dict[str, str]]) -> str:
    settings = get_settings()
    base = settings.llm_base_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    payload: dict[str, object] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": settings.llm_max_tokens,
    }
    if settings.llm_disable_reasoning:
        # Supported by LM Studio/vLLM-style local servers; disabled by default for cloud APIs.
        payload.update({"reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False}})
    async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
        response = await client.post(f"{base}/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        payload = response.json()
    try:
        content = str(payload["choices"][0]["message"]["content"])
        if not content.strip():
            raise ValueError("LLM response contained no displayable content")
        return content
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("LLM response did not contain chat content") from exc


async def briefing(session: Session, profile: str = "daily_chat") -> dict[str, object]:
    facts = _facts(session, profile)
    fallback = deterministic_briefing_from_facts(facts)
    settings = get_settings()
    if not settings.llm_enabled:
        return {"text": fallback, "source": "rules", "model": None}
    prompt = (
        "你是 API Radar 的 AI API 市场情报编辑。请根据 FACTS 写一篇 500-900 字的中文每日简报。"
        "优先写真正可行动的新变化：官方优惠、免费额度、价格变化、使用限制和风险；不要以规则分数或免费模型排行榜开头。"
        "status=changed 才能称为今天检测到页面变化；status=initial 只能说首次纳入监测，不能说今天发布；status=current 表示未检测到变化。"
        "如果没有 changed，可以从 status=current 中挑出当前仍然最值得利用的优惠或免费额度，但必须明确它不是今天新发布。"
        "事实只能来自 official_excerpt、verified_promotions 和 price_changes。每个重要事实必须附 FACTS 中的官方 Markdown 链接。"
        "若正文包含价格、额度、有效期、补充名额时间、适用工具或禁止用途，应准确提炼；没有明确证据就写未确认。"
        "最后给出清晰的今日行动建议，并区分订阅套餐与普通 API。不要杜撰，不要使用 HTML，不要泄露 FACTS 标签。"
        "FACTS=" + json.dumps(facts, ensure_ascii=False, default=str)
    )
    try:
        text = await _chat_completion([{"role": "system", "content": "你只使用提供的事实。"},
                                       {"role": "user", "content": prompt}])
        return {"text": text, "source": "llm", "model": settings.llm_model}
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"text": fallback, "source": "rules_fallback", "model": settings.llm_model,
                "error": repr(exc)}


async def chat(session: Session, messages: list[dict[str, str]], profile: str = "daily_chat") -> dict[str, object]:
    adjustment = update_preference_from_messages(session, messages)
    facts = _facts(session, profile)
    settings = get_settings()
    system = ("你是 API Radar 助手。只根据 FACTS 回答 Provider、价格和模型选择问题；"
              "明确区分已知事实和建议，不得杜撰。FACTS=" + str(facts))
    if settings.llm_enabled:
        try:
            text = await _chat_completion([{"role": "system", "content": system}, *messages[-12:]])
            return {"text": text, "source": "llm", "model": settings.llm_model, "adjustment": adjustment}
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {"text": deterministic_briefing_from_facts(facts), "source": "rules_fallback",
                    "model": settings.llm_model, "error": repr(exc), "adjustment": adjustment}
    return {"text": deterministic_briefing_from_facts(facts), "source": "rules", "model": None,
            "adjustment": adjustment}
