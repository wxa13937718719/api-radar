"""Run the configured public-provider scan workflow."""
import argparse
import asyncio

from api_radar.db import SessionLocal, create_all
from api_radar.providers import openrouter as _openrouter  # noqa: F401 -- registers provider
from api_radar.providers import siliconflow as _siliconflow  # noqa: F401 -- registers provider
from api_radar.providers.registry import registry
from api_radar.services.scanner import ProviderScanService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an API Radar provider scan")
    parser.add_argument("--dry-run", action="store_true", help="Initialize the database without network calls")
    parser.add_argument("--provider", choices=["all", "openrouter", "siliconflow"], default="all")
    args = parser.parse_args()
    create_all()
    if args.dry_run:
        print("API Radar database initialized; no network scan requested.")
        return 0
    with SessionLocal() as session:
        provider_ids = [args.provider] if args.provider != "all" else [item.metadata.provider_id for item in registry.all()]
        failed = False
        for provider_id in provider_ids:
            run = asyncio.run(ProviderScanService(session).scan(registry.get(provider_id)(), triggered_by="cli"))
            result = run.results[0]
            print(f"scan={run.id} status={run.status} provider={provider_id} models={result.models_count} prices={result.price_changes_count}")
            if result.error:
                failed = True
                print(f"error={result.error}")
        return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
