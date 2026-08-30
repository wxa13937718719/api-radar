"""Emit an explainable recommendation report for automation callers."""
import argparse
import asyncio
import json
import sys

from api_radar.db import SessionLocal, create_all
from api_radar.services.assistant import briefing
from api_radar.services.recommendations import PROFILES, generate_recommendations


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    create_all()
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=PROFILES, default="daily_chat")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    with SessionLocal() as session:
        recommendations = generate_recommendations(session, profile=args.profile, limit=args.limit)
        result = {"profile": args.profile, "recommendations": [
            {"provider_id": r.provider_id, "canonical_model_id": r.canonical_model_id,
             "score": str(r.total_score), "dimensions": r.dimension_scores, "reason": r.reason}
            for r in recommendations], "briefing": asyncio.run(briefing(session, args.profile))}
        print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
