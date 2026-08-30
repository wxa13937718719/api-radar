import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api_radar.db import Base
from api_radar.intelligence import OfficialSourceSpec, collect_official_sources
from api_radar.models import SourceSnapshot


async def test_official_source_snapshots_detect_real_content_changes() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    page = {"text": "首月 39.90 元"}

    def handler(request: httpx.Request) -> httpx.Response:
        body = f"<html><head><title>官方活动</title><script>ignore()</script></head><body>{page['text']}</body></html>"
        return httpx.Response(200, text=body, request=request)

    spec = (OfficialSourceSpec("promotion", "https://example.test/offer", "官方活动"),)
    transport = httpx.MockTransport(handler)
    first = await collect_official_sources(session, source_specs=spec, transport=transport)
    second = await collect_official_sources(session, source_specs=spec, transport=transport)
    page["text"] = "首月 29.90 元"
    third = await collect_official_sources(session, source_specs=spec, transport=transport)

    assert first[0].change_status == "initial"
    assert second[0].change_status == "unchanged"
    assert third[0].change_status == "changed"
    snapshots = session.scalars(select(SourceSnapshot).order_by(SourceSnapshot.id)).all()
    assert len(snapshots) == 3
    assert snapshots[-1].changed_since_previous is True
    assert "ignore" not in (snapshots[-1].safe_text or "")
    session.close()
