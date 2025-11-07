from __future__ import annotations
import requests, extruct
from w3lib.html import get_base_url
from .base import Extractor, RawItem, NormalizedEvent
from dateutil import parser as dtp
import hashlib


class SchemaOrgExtractor(Extractor):
    kind = "schema_org"

    def discover(self, source_url: str) -> list[RawItem]:
        r = requests.get(source_url, timeout=20)
        r.raise_for_status()
        data = extruct.extract(r.text, base_url=get_base_url(r.text, source_url), syntaxes=['json-ld'])
        items = []
        for obj in data.get('json-ld', []):
            t = obj.get("@type")
            if isinstance(t, list):
                is_event = "Event" in t
            else:
                is_event = (t == "Event")
            if is_event:
                items.append(RawItem(source_url=source_url, payload=obj))
        return items

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        out = []
        for it in items:
            p = it.payload
            title = p.get("name","" ).strip()
            start = p.get("startDate")
            end = p.get("endDate")
            venue = (p.get("location") or {}).get("name")
            addr = (p.get("location") or {}).get("address")
            desc = (p.get("description") or "").strip()
            url = p.get("url") or it.source_url
            start_iso = dtp.parse(start).isoformat() if start else None
            end_iso = dtp.parse(end).isoformat() if end else None
            uid = hashlib.sha1(f"{url}|{title}|{start_iso}".encode()).hexdigest()[:20]
            data = {
                "uid": uid, "source_url": url,
                "title": title, "description": desc, "category": "general",
                "age_min": None, "age_max": None, "start_dt": start_iso, "end_dt": end_iso,
                "tz": "America/New_York", "venue_name": venue, "address": str(addr) if addr else None,
                "lat": None, "lng": None, "cost_min": None, "cost_max": None,
                "registration_url": url, "tags": {}
            }
            out.append(NormalizedEvent(uid=uid, data=data))
        return out

