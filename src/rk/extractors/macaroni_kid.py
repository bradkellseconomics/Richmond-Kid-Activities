# macaroni_kid.py
#
# Macaroni KID publishes its event calendar through a plain JSON API
# (the same one its own event-list page calls via jQuery). Hitting it
# directly is far simpler and more reliable than driving a browser:
# no Playwright/xvfb, no anti-bot friction, and every event ships a
# clean ISO start/end datetime plus a structured age range, so we don't
# need to regex-parse dates or ages out of rendered HTML.
from __future__ import annotations
import hashlib
import html as html_mod
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from selectolax.parser import HTMLParser
from dateutil import tz as dttz

from .base import Extractor, RawItem, NormalizedEvent

DEBUG = os.getenv("RK_DEBUG", "0") == "1"
LOCAL_TZ = dttz.gettz("America/New_York")

LOOKAHEAD_DAYS = int(os.getenv("RK_MACKID_LOOKAHEAD_DAYS", "60"))

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 rk-bot/1.0"
    ),
    "Accept": "application/json",
}

TOWN_ID_RE = re.compile(r'data-town="([0-9a-f]{24})"', re.I)


def dprint(*args):
    if DEBUG:
        print("[DEBUG][macaronikid]", *args)


def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    try:
        text = HTMLParser(s).text(separator=" ").strip()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", s)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _first_href(html_fragment: str | None) -> str | None:
    if not html_fragment:
        return None
    m = re.search(r'href="([^"]+)"', html_fragment)
    return m.group(1) if m else None


def _slugify(title: str) -> str:
    s = (title or "").lower()
    s = re.sub(r"[/\s]+", "-", s)
    s = re.sub(r"[,\"!%@:]", "", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "event"


def _parse_cost(cost_raw: str | None) -> tuple[float | None, float | None]:
    if not cost_raw:
        return None, None
    s = cost_raw.strip()
    if not s or s == "0" or re.search(r"\bfree\b", s, re.I):
        return 0.0, 0.0
    amounts = [float(x) for x in re.findall(r"\$([0-9]+(?:\.[0-9]{1,2})?)", s)]
    if amounts:
        return min(amounts), max(amounts)
    return None, None


def _format_address(addr: dict | None) -> str | None:
    if not addr:
        return None
    parts = [addr.get("street1"), addr.get("city"), addr.get("state"), addr.get("zipCode")]
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _to_local_iso(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    try:
        d = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return d.astimezone(LOCAL_TZ).isoformat()
    except Exception:
        return None


class MacaroniKidExtractor(Extractor):
    kind = "macaronikid"

    def _town_id(self, site_base: str) -> str | None:
        try:
            r = requests.get(f"{site_base}/events", headers=UA, timeout=25)
            r.raise_for_status()
        except Exception as e:
            dprint(f"failed to load events page for town id: {e}")
            return None
        m = TOWN_ID_RE.search(r.text)
        return m.group(1) if m else None

    def discover(self, source_url: str) -> list[RawItem]:
        u = urlparse(source_url)
        site_base = f"{u.scheme}://{u.netloc}"

        town_id = self._town_id(site_base)
        if not town_id:
            print(f"[WARN] macaronikid: could not resolve town id from {source_url}")
            return []

        start = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "T04:00:00.000Z"
        end = (datetime.now(timezone.utc) + timedelta(days=LOOKAHEAD_DAYS)).strftime("%Y-%m-%d") + "T03:59:59.000Z"
        query = json.dumps({"status": "active", "townOwner": town_id, "startDate": start, "endDate": end})
        api_url = f"https://api.macaronikid.com/api/v1/event/v2?query={query}&impression=true&limit=801"

        try:
            r = requests.get(api_url, headers={**UA, "Referer": f"{site_base}/events"}, timeout=30)
            r.raise_for_status()
            events = r.json()
        except Exception as e:
            print(f"[WARN] macaronikid: API request failed: {e}")
            return []

        if DEBUG:
            dbg_dir = os.path.join("data", "debug", "macaroni_kid")
            os.makedirs(dbg_dir, exist_ok=True)
            with open(os.path.join(dbg_dir, "api_response.json"), "w", encoding="utf-8") as f:
                json.dump(events, f, ensure_ascii=False, indent=2)

        dprint(f"town_id={town_id} lookahead_days={LOOKAHEAD_DAYS} events={len(events)}")

        items = []
        for ev in events:
            if ev.get("hidden"):
                continue
            eid = ev.get("id") or ev.get("_id")
            if not eid or not ev.get("startDateTime"):
                continue
            detail_url = f"{site_base}/events/{eid}/{_slugify(ev.get('title'))}"
            items.append(RawItem(source_url=detail_url, payload=ev))
        return items

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        out = []
        for it in items:
            ev = it.payload
            title = (ev.get("title") or "").strip()
            start_iso = _to_local_iso(ev.get("startDateTime"))
            if not title or not start_iso:
                continue
            end_iso = _to_local_iso(ev.get("endDateTime"))

            cats = ev.get("categories") or []
            category = (cats[0].get("name") if cats and isinstance(cats[0], dict) else None) or "general"

            who_txt = _strip_html(ev.get("who"))
            how_txt = _strip_html(ev.get("how"))
            desc_parts = []
            if who_txt and who_txt not in ("-", "0"):
                desc_parts.append(f"Ages: {who_txt}")
            if how_txt:
                desc_parts.append(how_txt)
            description = " | ".join(desc_parts)

            age_min = age_max = None
            age_range = ev.get("targetAgeRange")
            if isinstance(age_range, dict):
                age_min = age_range.get("minAge")
                age_max = age_range.get("maxAge")

            cost_min, cost_max = _parse_cost(ev.get("cost"))
            registration_url = _first_href(ev.get("how")) or it.source_url

            uid = hashlib.sha1(f"{it.source_url}|{title}|{start_iso}".encode()).hexdigest()[:20]
            data = {
                "uid": uid,
                "source_url": it.source_url,
                "title": title,
                "description": description,
                "category": category.lower(),
                "age_min": age_min,
                "age_max": age_max,
                "start_dt": start_iso,
                "end_dt": end_iso,
                "tz": "America/New_York",
                "venue_name": (ev.get("where") or "").strip() or None,
                "address": _format_address(ev.get("address")),
                "lat": None,
                "lng": None,
                "cost_min": cost_min,
                "cost_max": cost_max,
                "registration_url": registration_url,
                "tags": {"categories": [c.get("name") for c in cats if isinstance(c, dict)]},
            }
            out.append(NormalizedEvent(uid=uid, data=data))
        return out
