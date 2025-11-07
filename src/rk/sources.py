from __future__ import annotations
from sqlalchemy import select
from .db import SessionLocal
from .models import Source


DEFAULT_SOURCES = [
    # Start with structured or ICS if available; add HTML pages next.
    {"name": "Children's Museum of Richmond (Events)", "url": "https://www.childrensmuseumofrichmond.org/events/", "kind": "html"},
    {"name": "Science Museum of Virginia (Calendar)", "url": "https://smv.org/calendar/", "kind": "html"},
    {"name": "Richmond Public Library (Events)", "url": "https://rvalibrary.org/events/", "kind": "html"},
    {"name": "VMFA (Events)", "url": "https://vmfa.museum/calendar/", "kind": "html"},
    {"name": "Maymont (Events)", "url": "https://maymont.org/events/", "kind": "html"},
    {"name": "Lewis Ginter Garden (Events)", "url": "https://www.lewisginter.org/events/", "kind": "html"},
    {"name": "City Parks & Rec (News/Calendar)", "url": "https://rva.gov/parks-recreation", "kind": "html"},
]


def ensure_sources():
    with SessionLocal() as s:
        for src in DEFAULT_SOURCES:
            exists = s.scalars(select(Source).where(Source.url == src["url"])).first()
            if not exists:
                s.add(Source(**src))
        s.commit()

