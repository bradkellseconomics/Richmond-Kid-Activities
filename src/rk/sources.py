from __future__ import annotations
from sqlalchemy import select
from .db import SessionLocal
from .models import Source


DEFAULT_SOURCES = [
    # Prefer structured feeds when available; fall back to HTML.
    {"name": "Maymont (ICS)", "url": "https://maymont.org/events/?ical=1", "kind": "ics"},
    {"name": "Lewis Ginter Garden (ICS)", "url": "https://www.lewisginter.org/events/?ical=1", "kind": "ics"},
    {"name": "Belmont Library (ICS)", "url": "https://rvalibrary.libcal.com/ical_subscribe.php?src=p&cid=7752", "kind": "ics"},
    {"name": "Main Library (ICS)", "url": "https://rvalibrary.libcal.com/ical_subscribe.php?src=p&cid=7469", "kind": "ics"},
    {"name": "Henrico County Library (ICS)", "url": "https://henricolibrary-va.libcal.com/ical_subscribe.php?src=p&cid=12755", "kind": "ics"},
    {"name": "Richmond Cultureworks (ICS)", "url": "https://calendar.richmondcultureworks.org/calendar.ics", "kind": "ics"},
    {"name": "Macaroni KID Richmond", "url": "https://richmond.macaronikid.com/events", "kind": "macaronikid"},
] 


def ensure_sources():
    with SessionLocal() as s:
        for src in DEFAULT_SOURCES:
            # Match by name first, falling back to URL (e.g. after a rename
            # in DEFAULT_SOURCES) so an existing row gets updated in place
            # rather than silently left stale.
            existing = s.scalars(select(Source).where(Source.name == src["name"])).first()
            if not existing:
                existing = s.scalars(select(Source).where(Source.url == src["url"])).first()
            if existing:
                changed = False
                if existing.name != src["name"]:
                    existing.name = src["name"]; changed = True
                if existing.url != src["url"]:
                    existing.url = src["url"]; changed = True
                if existing.kind != src["kind"]:
                    existing.kind = src["kind"]; changed = True
                if existing.active != 1:
                    existing.active = 1; changed = True
                if changed:
                    s.add(existing)
            else:
                s.add(Source(**src))
        s.commit()
