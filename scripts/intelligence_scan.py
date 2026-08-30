"""Capture official market-intelligence sources and report change status."""
from __future__ import annotations

import asyncio
import json

from api_radar.db import SessionLocal, create_all
from api_radar.intelligence import collect_official_sources


def main() -> int:
    create_all()
    with SessionLocal() as session:
        results = asyncio.run(collect_official_sources(session))
    print(json.dumps({
        "sources": len(results),
        "successful": sum(item.success for item in results),
        "changed": sum(item.change_status == "changed" for item in results),
        "initial": sum(item.change_status == "initial" for item in results),
        "results": [item.__dict__ for item in results],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
