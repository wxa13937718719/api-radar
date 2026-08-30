from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def create_all() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # ``create_all`` intentionally does not alter existing SQLite tables.  Keep
    # the desktop app self-upgrading for additive columns introduced between
    # releases, without requiring a migration CLI for local users.
    if engine.dialect.name == "sqlite":
        _ensure_sqlite_columns()


def _ensure_sqlite_columns() -> None:
    additions = {
        "providers": {
            "official_url": "VARCHAR(500)", "pricing_url": "VARCHAR(500)",
            "api_base_url": "VARCHAR(500)", "provider_type": "VARCHAR(50) DEFAULT 'api_provider'",
            "country_or_region": "VARCHAR(100)", "discovery_source": "VARCHAR(500)",
            "discovered_at": "DATETIME", "last_checked_at": "DATETIME",
            "status": "VARCHAR(30) DEFAULT 'supported'", "parser_status": "VARCHAR(30) DEFAULT 'ready'",
            "has_pricing_page": "BOOLEAN DEFAULT 0", "has_model_api": "BOOLEAN DEFAULT 0",
            "login_required": "BOOLEAN DEFAULT 0", "data_confidence": "NUMERIC(5,4) DEFAULT 0.5",
            "priority_score": "INTEGER DEFAULT 0", "ignored": "BOOLEAN DEFAULT 0",
        },
        "price_snapshots": {
            "validation_status": "VARCHAR(20) DEFAULT 'verified'", "identity_status": "VARCHAR(20) DEFAULT 'verified'",
            "confidence": "NUMERIC(5,4) DEFAULT 1.0", "invalid_reason": "VARCHAR(300)",
        },
        "model_price": {
            "validation_status": "VARCHAR(20) DEFAULT 'verified'", "identity_status": "VARCHAR(20) DEFAULT 'verified'",
            "confidence": "NUMERIC(5,4) DEFAULT 1.0", "invalid_reason": "VARCHAR(300)",
        },
        "provider_offers": {
            "interaction_mode": "VARCHAR(30) DEFAULT 'realtime'",
            "speed_score": "NUMERIC(5,2)", "stability_score": "NUMERIC(5,2)",
            "compatibility_score": "NUMERIC(5,2)", "channel_risk": "VARCHAR(20) DEFAULT 'unknown'",
        },
        "user_assets": {
            "has_account": "BOOLEAN DEFAULT 0", "credit_exchange_rate": "NUMERIC(20,8)",
            "subscription": "VARCHAR(300)", "primary_or_backup": "VARCHAR(20) DEFAULT 'primary'",
            "notes": "TEXT",
        },
    }
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))
        # Existing rows predate the registry fields; make their state explicit.
        connection.execute(text("UPDATE providers SET status = COALESCE(status, 'supported'), parser_status = COALESCE(parser_status, 'ready'), provider_type = COALESCE(provider_type, 'api_provider'), data_confidence = COALESCE(data_confidence, 0.5), priority_score = COALESCE(priority_score, 0), ignored = COALESCE(ignored, 0), has_pricing_page = CASE WHEN pricing_source IS NOT NULL AND (has_pricing_page IS NULL OR has_pricing_page = 0) THEN 1 ELSE COALESCE(has_pricing_page, 0) END, has_model_api = COALESCE(has_model_api, 1), login_required = COALESCE(login_required, 0), discovered_at = COALESCE(discovered_at, CURRENT_TIMESTAMP)"))
        connection.execute(text("UPDATE price_snapshots SET validation_status = COALESCE(validation_status, 'verified'), identity_status = COALESCE(identity_status, 'verified'), confidence = COALESCE(confidence, 1.0)"))
        connection.execute(text("UPDATE model_price SET validation_status = COALESCE(validation_status, 'verified'), identity_status = COALESCE(identity_status, 'verified'), confidence = COALESCE(confidence, 1.0)"))
        connection.execute(text("UPDATE provider_offers SET interaction_mode = COALESCE(interaction_mode, 'realtime'), channel_risk = COALESCE(channel_risk, 'unknown')"))
        connection.execute(text("UPDATE user_assets SET has_account = COALESCE(has_account, CASE WHEN api_key_status = 'active' THEN 1 ELSE 0 END), primary_or_backup = COALESCE(primary_or_backup, 'primary')"))


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
