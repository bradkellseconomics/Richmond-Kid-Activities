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
        # Create client only if key is present to allow offline testing
        self.client = OpenAI(api_key=CFG.openai_api_key) if CFG.openai_api_key else None

    def discover(self, source_url: str) -> list[RawItem]:
        from urllib.parse import urlparse, urlunparse

        def _fetch(url: str):
            return requests.get(
                url,
                timeout=25,
                headers={"User-Agent": "rk-bot/1.0 (+https://github.com/)"},
            )

        try:
            r = _fetch(source_url)
            r.raise_for_status()
        except requests.exceptions.SSLError:
            # Retry without 'www.' (common cert mismatch)
            try:
                u = urlparse(source_url)
                host = u.netloc.replace("www.", "")
                fallback = urlunparse((u.scheme, host, u.path, u.params, u.query, u.fragment))
                r = _fetch(fallback)
                r.raise_for_status()
            except Exception as e2:
                print(f"[WARN] SSL issue for {source_url}; fallback failed: {e2}")
                return []
        except Exception as e:
            print(f"[WARN] HTMLLLMExtractor discover failed for {source_url}: {e}")
            return []

        html = HTMLParser(r.text)
        main = html.css_first("main") or html.css_first("article") or html
        text = main.text(separator="\n")
        return [RawItem(source_url=source_url, payload={"text": text})]

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        # If no client/API key, skip LLM extraction gracefully
        if not self.client:
            print("[WARN] OPENAI_API_KEY not set; skipping HTML extraction")
            return []

        out = []
        import json, re
        for it in items:
            try:
                text = it.payload['text']
                chunks = [text[i:i+6000] for i in range(0, len(text), 6000)] or [text]
                merged = {"events": []}
                for ch in chunks[:3]:  # cap to 3 chunks for cost
                    resp = self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    SYS
                                    + " Output strictly valid JSON with a top-level 'events' array."
                                    + " Each event object should only use the fields in the schema."
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"Source URL: {it.source_url}\n\n{ch}",
                            },
                        ],
                        temperature=0,
                        response_format={"type": "json_object"},
                    )
                    content = resp.choices[0].message.content or "{}"
                    content = re.sub(r"^```(json)?|```$", "", content.strip(), flags=re.MULTILINE)
                    data = json.loads(content)
                    if isinstance(data, dict) and isinstance(data.get("events"), list):
                        merged["events"].extend(data["events"])
                data = merged
            except Exception as e:
                print(f"[WARN] LLM parse failed for {it.source_url}: {e}")
                continue

            for ev in data.get("events", []):
                try:
                    start_iso = dtp.parse(ev["start_dt"]).isoformat()
                except Exception:
                    continue
                end_iso = None
                if ev.get("end_dt"):
                    try:
                        end_iso = dtp.parse(ev["end_dt"]).isoformat()
                    except Exception:
                        end_iso = None
                uid = hashlib.sha1(f"{it.source_url}|{ev['title']}|{start_iso}".encode()).hexdigest()[:20]
                norm = {
                    "uid": uid,
                    "source_url": it.source_url,
                    "title": ev.get("title", "").strip(),
                    "description": (ev.get("description") or "").strip(),
                    "category": (ev.get("category") or "general"),
                    "age_min": ev.get("age_min"),
                    "age_max": ev.get("age_max"),
                    "start_dt": start_iso,
                    "end_dt": end_iso,
                    "tz": "America/New_York",
                    "venue_name": ev.get("venue_name"),
                    "address": ev.get("address"),
                    "lat": None,
                    "lng": None,
                    "cost_min": ev.get("cost_min"),
                    "cost_max": ev.get("cost_max"),
                    "registration_url": ev.get("registration_url") or it.source_url,
                    "tags": {},
                }
                out.append(NormalizedEvent(uid=uid, data=norm))
        return out


def _text_trim(s: str, max_chars: int) -> str:
    return s if len(s) <= max_chars else s[:max_chars]

