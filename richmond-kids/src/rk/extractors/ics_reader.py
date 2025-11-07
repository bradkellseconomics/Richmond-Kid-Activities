from __future__ import annotations
import requests, hashlib
from ics import Calendar
from dateutil import tz
from .base import Extractor, RawItem, NormalizedEvent


class ICSExtractor(Extractor):
    kind = "ics"

    def discover(self, source_url: str) -> list[RawItem]:
        r = requests.get(source_url, timeout=20)
        r.raise_for_status()
        return [RawItem(source_url=source_url, payload={"ics": r.text})]

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        out = []
        for it in items:
            cal = Calendar(it.payload["ics"])
            for e in cal.events:
                title = (e.name or "").strip()
                start_iso = e.begin.astimezone(tz.gettz("America/New_York")).isoformat() if e.begin else None
                end_iso = e.end.astimezone(tz.gettz("America/New_York")).isoformat() if e.end else None
                uid = hashlib.sha1(f"{it.source_url}|{title}|{start_iso}".encode()).hexdigest()[:20]
                data = {
                    "uid": uid, "source_url": it.source_url, "title": title,
                    "description": (e.description or "").strip(),
                    "category": "general", "age_min": None, "age_max": None,
                    "start_dt": start_iso, "end_dt": end_iso, "tz": "America/New_York",
                    "venue_name": (e.location or None), "address": None, "lat": None, "lng": None,
                    "cost_min": None, "cost_max": None, "registration_url": None, "tags": {}
                }
                out.append(NormalizedEvent(uid=uid, data=data))
        return out

