"""Background scan orchestration for HTTP callers."""
from __future__ import annotations

import asyncio

from ..db import SessionLocal
from ..intelligence import collect_official_sources
from ..providers.registry import registry
from .scanner import ProviderScanService


def run_scan_job(provider_ids: list[str]) -> None:
    """Run providers serially so failures remain isolated and SQLite writes stay simple."""
    with SessionLocal() as session:
        for provider_id in provider_ids:
            asyncio.run(ProviderScanService(session).scan(registry.get(provider_id)(), triggered_by="api"))


def run_intelligence_job() -> None:
    with SessionLocal() as session:
        asyncio.run(collect_official_sources(session))
