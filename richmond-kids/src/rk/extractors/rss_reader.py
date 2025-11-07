from __future__ import annotations
import feedparser, hashlib
from .base import Extractor, RawItem, NormalizedEvent


class RSSExtractor(Extractor):
    kind = "rss"

    def discover(self, source_url: str) -> list[RawItem]:
        feed = feedparser.parse(source_url)
        items = []
        for e in feed.entries:
            items.append(RawItem(source_url=e.link, payload={
                "title": e.title, "summary": getattr(e, "summary", ""), "published": getattr(e, "published", None),
                "link": e.link
            }))
        return items

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        out = []
        for it in items:
            title = it.payload["title"].strip()
            start_iso = None
            uid = hashlib.sha1(f"{it.source_url}|{title}".encode()).hexdigest()[:20]
            data = {
                "uid": uid, "source_url": it.source_url, "title": title,
                "description": it.payload.get("summary",""),
                "category": "general", "age_min": None, "age_max": None,
                "start_dt": start_iso, "end_dt": None, "tz": "America/New_York",
                "venue_name": None, "address": None, "lat": None, "lng": None,
                "cost_min": None, "cost_max": None, "registration_url": it.source_url, "tags": {}
            }
            out.append(NormalizedEvent(uid=uid, data=data))
        return out

