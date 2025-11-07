from __future__ import annotations
import requests, hashlib
from selectolax.parser import HTMLParser
from .base import Extractor, RawItem, NormalizedEvent
from dateutil import parser as dtp
from openai import OpenAI
from ..config import CFG


EVENTS_SCHEMA = {
  "name": "EventList",
  "schema": {
    "type": "object",
    "properties": {
      "events": {
        "type": "array",
        "items": {
          "type":"object",
          "properties": {
            "title": {"type":"string"},
            "description": {"type":"string"},
            "category": {"type":"string"},
            "age_min": {"type":"integer", "minimum":0},
            "age_max": {"type":"integer", "minimum":0},
            "start_dt": {"type":"string", "pattern":"^\\d{4}-\\d{2}-\\d{2}T.*$"},
            "end_dt": {"type":["string","null"]},
            "venue_name": {"type":["string","null"]},
            "address": {"type":["string","null"]},
            "cost_min": {"type":["number","null"]},
            "cost_max": {"type":["number","null"]},
            "registration_url": {"type":["string","null"]}
          },
          "required": ["title","start_dt"]
        }
      }
    },
    "required": ["events"],
    "additionalProperties": False
  }
}

SYS = (
  "Extract children-friendly events in Richmond, VA. Return ONLY fields asked in schema. "
  "Parse dates to ISO-8601 with local timezone if present; prefer explicit dates over relative words."
)


class HTMLLLMExtractor(Extractor):
    kind = "html"

    def __init__(self):
        self.client = OpenAI(api_key=CFG.openai_api_key)

    def discover(self, source_url: str) -> list[RawItem]:
        r = requests.get(source_url, timeout=25)
        r.raise_for_status()
        html = HTMLParser(r.text)
        main = html.css_first("main") or html.css_first("article") or html
        text = main.text(separator="\n")
        return [RawItem(source_url=source_url, payload={"text": text})]

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        out = []
        for it in items:
            resp = self.client.responses.create(
              model="gpt-5",
              input=[{"role":"system","content":SYS},
                     {"role":"user","content": f"Source URL: {it.source_url}\n\n{_text_trim(it.payload['text'], 8000)}"}],
              response_format={"type":"json_schema", "json_schema": EVENTS_SCHEMA},
            )
            data = resp.output_parsed
            for ev in data.get("events", []):
                start_iso = dtp.parse(ev["start_dt"]).isoformat()
                end_iso = dtp.parse(ev["end_dt"]).isoformat() if ev.get("end_dt") else None
                uid = hashlib.sha1(f"{it.source_url}|{ev['title']}|{start_iso}".encode()).hexdigest()[:20]
                norm = {
                    "uid": uid, "source_url": it.source_url, "title": ev["title"].strip(),
                    "description": (ev.get("description") or "").strip(),
                    "category": (ev.get("category") or "general"),
                    "age_min": ev.get("age_min"), "age_max": ev.get("age_max"),
                    "start_dt": start_iso, "end_dt": end_iso, "tz":"America/New_York",
                    "venue_name": ev.get("venue_name"), "address": ev.get("address"),
                    "lat": None, "lng": None,
                    "cost_min": ev.get("cost_min"), "cost_max": ev.get("cost_max"),
                    "registration_url": ev.get("registration_url") or it.source_url,
                    "tags": {}
                }
                out.append(NormalizedEvent(uid=uid, data=norm))
        return out


def _text_trim(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[:max_chars]

