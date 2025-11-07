from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import engine, SessionLocal, Base
from .models import Source, Event
from .extractors.schema_org import SchemaOrgExtractor
from .extractors.rss_reader import RSSExtractor
from .extractors.ics_reader import ICSExtractor
from .extractors.html_llm import HTMLLLMExtractor
from .scoring import score_event
from dateutil import parser as dtp
from .config import CFG


EXTRACTORS = {
    "schema_org": SchemaOrgExtractor(),
    "rss": RSSExtractor(),
    "ics": ICSExtractor(),
    "html": HTMLLLMExtractor(),
}


def init_db():
    # Ensure the parent directory for SQLite exists
    db_dir = os.path.dirname(CFG.db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    Base.metadata.create_all(engine)


def upsert_events(session, source: Source, events: list[dict]) -> int:
    added = 0
    now = datetime.now(timezone.utc)
    for d in events:
        ev = Event(**d, source_id=source.id, first_seen=now, last_seen=now, status="active")
        try:
            session.add(ev)
            session.commit()
            added += 1
        except IntegrityError:
            session.rollback()
    return added


def harvest():
    init_db()
    with SessionLocal() as s:
        sources = list(s.scalars(select(Source).where(Source.active == 1)))
        total = 0
        for src in sources:
            ex = EXTRACTORS.get(src.kind)
            if not ex:
                continue
            raw = ex.discover(src.url)
            norm = [n.data for n in ex.normalize(raw)]
            total += upsert_events(s, src, norm)
        return total


def window_next_week(start_day="sat"):
    # Saturday through Friday window
    today = datetime.now().astimezone()
    offset = (5 - today.weekday()) % 7 if start_day == "sat" else 0
    start = (today + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return start, end


def select_and_score():
    start, end = window_next_week("sat")
    with SessionLocal() as s:
        evs = list(s.scalars(select(Event)))
        picked = []
        for e in evs:
            try:
                st = dtp.parse(e.start_dt)
            except Exception:
                continue
            if not (start <= st <= end):
                continue
            d = {c.name: getattr(e, c.name) for c in Event.__table__.columns}
            d["_score"] = score_event(d)
            picked.append(d)
        picked.sort(key=lambda x: x["_score"], reverse=True)
        return picked[:12], picked[12:40]

