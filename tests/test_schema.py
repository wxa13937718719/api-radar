from sqlalchemy import create_engine, inspect

from api_radar import models  # noqa: F401
from api_radar.db import Base


def test_phase_a_schema_creates_all_core_tables() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"providers", "models", "provider_models", "model_aliases", "price_snapshots", "promotions", "sources", "recommendations", "scan_runs", "scan_results"} <= tables
