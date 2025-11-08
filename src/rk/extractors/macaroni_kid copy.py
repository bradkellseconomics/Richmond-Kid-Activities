from __future__ import annotations
import hashlib, os, re, time
from typing import List, Optional
from urllib.parse import urljoin
from datetime import datetime

import extruct
from selectolax.parser import HTMLParser
from w3lib.html import get_base_url
from dateutil import parser as dtp
from dateutil import tz as dttz
import html as html_mod

from .base import Extractor, RawItem, NormalizedEvent

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 rk-bot/1.0"
    )
}

DEBUG = os.getenv("RK_DEBUG", "0") == "1"

def dprint(*args):
    if DEBUG:
        print("[DEBUG]", *args)

# -----------------------------------------------------------------------------
# Sanitizers and time helpers
# -----------------------------------------------------------------------------
# Stronger sanitizers to strip inline JS, script/style tags, and sponsor URLs
SCRIPT_TAG_PAT = re.compile(r"<script\b[^>]*>[\s\S]*?</script>", re.I)
STYLE_TAG_PAT = re.compile(r"<style\b[^>]*>[\s\S]*?</style>", re.I)
SPONSOR_URL_PAT = re.compile(r"https?://sponsors\.macaronikid\.com[:/\w\-\.\?\=&%]*", re.I)
QS_LISTENER_PAT = re.compile(
    r"document\.querySelector\([^)]+\)\.addEventListener\([^)]*\)\s*\{[\s\S]*?\}\s*;?",
    re.I,
)


def _clean_text(s: str) -> str:
    if not s:
        return ""
    # Strip tags and obvious inline JS/trackers
    s = SCRIPT_TAG_PAT.sub(" ", s)
    s = STYLE_TAG_PAT.sub(" ", s)
    s = QS_LISTENER_PAT.sub(" ", s)
    s = SPONSOR_URL_PAT.sub(" ", s)
    # Unescape entities and collapse whitespace
    s = html_mod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_visible_text(html_str: str, selector: str | None = None, max_len: int = 2000) -> str:
    try:
        doc = HTMLParser(html_str)
        node = doc.css_first(selector) if selector else (doc.body or doc.root)
        if not node:
            return ""
        # remove script/style/noscript nodes entirely
        for n in node.css("script, style, noscript"):
            n.decompose()
        txt = node.text(separator=" ").strip()
        return _clean_text(txt)[:max_len]
    except Exception:
        return ""


LOCAL_TZ = dttz.gettz("America/New_York")


def _to_local_iso(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    try:
        d = dtp.parse(dt_str)
        if d.tzinfo is None:
            d = d.replace(tzinfo=LOCAL_TZ)
        else:
            d = d.astimezone(LOCAL_TZ)
        return d.isoformat()
    except Exception:
        return None


def _find_html_times(html: str) -> tuple[str | None, str | None]:
    try:
        doc = HTMLParser(html)
        t_start = doc.css_first('time[itemprop="startDate"], time[datetime]')
        t_end = doc.css_first('time[itemprop="endDate"]')
        s_iso = _to_local_iso(t_start.attributes.get("datetime")) if t_start and t_start.attributes.get("datetime") else None
        e_iso = _to_local_iso(t_end.attributes.get("datetime")) if t_end and t_end.attributes.get("datetime") else None
        if s_iso or e_iso:
            return (s_iso, e_iso)
    except Exception:
        pass

    # Textual fallback like: "When: Tue Nov 11, 10:30 AM – 11:15 AM"
    try:
        text = _extract_visible_text(
            html,
            selector=".event, .event-content, article, main, .content",
            max_len=4000,
        )
        m = re.search(
            r"(When|Date)\s*:\s*([A-Za-z]{3,9}\.?\,?\s*)?"
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{1,2}[^,\n]*?(am|pm|AM|PM)(?:\s*[-–]\s*[^,\n]*?(am|pm|AM|PM))?",
            text,
            re.I,
        )
        if m:
            return (_to_local_iso(m.group(0)), None)
    except Exception:
        pass

    return (None, None)


def _meta_og_description(html: str) -> str | None:
    try:
        doc = HTMLParser(html)
        m = doc.css_first('meta[property="og:description"], meta[name="description"]')
        if m and m.attributes.get("content"):
            return m.attributes["content"].strip()
    except Exception:
        pass
    return None

# -----------------------------------------------------------------------------
# Playwright context helper (imported lazily so local runs work without it)
# -----------------------------------------------------------------------------
def _playwright_context():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        print(f"[DEBUG] macaroni_kid: playwright import FAILED -> {e}")
        return None, None, None

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(
        user_agent=UA["User-Agent"],
        viewport={"width": 1366, "height": 900},
        locale="en-US",
    )
    return pw, browser, ctx

# -----------------------------------------------------------------------------
# Minimal HTML fallback parser used only for detail pages as a last resort
# -----------------------------------------------------------------------------
def _parse_jsonld(html: str, page_url: str) -> list[dict]:
    out: list[dict] = []
    try:
        data = extruct.extract(html, base_url=get_base_url(html, page_url), syntaxes=["json-ld"])
    except Exception:
        data = {"json-ld": []}
    for obj in data.get("json-ld", []):
        objs = obj.get("@graph") if isinstance(obj, dict) and "@graph" in obj else [obj]
        for o in objs:
            t = o.get("@type")
            is_event = ("Event" in t) if isinstance(t, list) else (t == "Event")
            if not is_event:
                continue
            title = _clean_text((o.get("name") or "").strip())
            start_iso = _to_local_iso(o.get("startDate"))
            end_iso = _to_local_iso(o.get("endDate"))
            desc = _clean_text((o.get("description") or "").strip())
            # Fill blanks from HTML if times missing
            if not start_iso or not end_iso:
                s2, e2 = _find_html_times(html)
                start_iso = start_iso or s2
                end_iso = end_iso or e2
            # Prefer meta description if JSON-LD desc is empty
            if not desc:
                desc = _clean_text(_meta_og_description(html) or "")
            loc = o.get("location") or {}
            venue = loc.get("name") if isinstance(loc, dict) else None
            addr = loc.get("address") if isinstance(loc, dict) else None
            out.append({
                "title": title,
                "description": desc,
                "start_dt": start_iso,
                "end_dt": end_iso,
                "venue_name": venue,
                "address": str(addr) if addr else None,
                "registration_url": o.get("url") or page_url,
            })
    return out

def _parse_html_light(html: str, page_url: str) -> list[dict]:
    try:
        doc = HTMLParser(html)
        tn = doc.css_first("h1") or doc.css_first("h2") or doc.css_first("title")
        title = _clean_text(tn.text(separator=" ").strip()) if tn else ""
    except Exception:
        title = ""

    s_iso, e_iso = _find_html_times(html)

    # Prefer meta og:description, then visible body
    desc = _meta_og_description(html) or _extract_visible_text(
        html,
        selector=".event, .event-content, article, main, .content",
    )
    desc = _clean_text(desc)

    if not s_iso:
        m = re.search(
            r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?.{0,20}?"
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+\d{1,2}.*?\d{4}.*?(?:am|pm|AM|PM)?",
            desc,
            re.I,
        )
        if m:
            s_iso = _to_local_iso(m.group(0))

    return [{
        "title": title,
        "description": desc,
        "start_dt": s_iso,
        "end_dt": e_iso,
        "venue_name": None,
        "address": None,
        "registration_url": page_url,
    }]

# -----------------------------------------------------------------------------
# Extractor
# -----------------------------------------------------------------------------
class MacaroniKidExtractor(Extractor):
    """
    Render the JS list view, click weekday tabs, scroll to trigger lazy-load,
    collect /events/<slug> links, then fetch each event page (rendered HTML).
    """
    kind = "macaronikid"

    def discover(self, source_url: str) -> List[RawItem]:
        pw, browser, ctx = _playwright_context()
        if not pw:
            print("[WARN] Macaroni KID requires a real browser; falling back will miss events.")
            return []

        detail_items: list[RawItem] = []
        MAX_EVENTS = 350  # safety cap

        try:
            p = ctx.new_page()
            p.set_default_timeout(20000)
            dprint(f"Go to {source_url}")
            p.goto(source_url, wait_until="domcontentloaded")
            p.wait_for_timeout(1200)

            # Click visible day tabs (helps hydrate lists)
            try:
                tabs = p.locator("a, button").filter(
                    has_text=r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b"
                ).all()
                for t in tabs[:7]:
                    try:
                        t.click()
                        p.wait_for_timeout(300)
                    except Exception:
                        pass
            except Exception:
                pass

            # Scroll a few times to trigger lazy-load
            for _ in range(4):
                p.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                p.wait_for_timeout(600)

            # Collect event links
            hrefs = p.eval_on_selector_all(
                "a[href*='/events/']",
                "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
            )
            links = sorted({
                urljoin(p.url, h) for h in hrefs
                if "/events/calendar" not in h and "/events/submit" not in h
            })
            dprint(f"found {len(links)} event links")

            # Visit each event page and stash rendered HTML
            for i, ev_url in enumerate(links):
                if len(detail_items) >= MAX_EVENTS:
                    break
                try:
                    dp = ctx.new_page()
                    dp.set_default_timeout(20000)
                    dp.goto(ev_url, wait_until="domcontentloaded")
                    dp.wait_for_timeout(800)
                    html = dp.content()
                    detail_items.append(RawItem(source_url=ev_url, payload={"html": html}))
                    dp.close()
                    if DEBUG and (i % 25 == 0):
                        print(f"[DEBUG] captured {i+1}/{len(links)} -> {ev_url}")
                    # polite throttle
                    time.sleep(0.15)
                except Exception as e:
                    print(f"[WARN] MacaroniKid event fetch failed: {ev_url} -> {e}")

            p.close()
        finally:
            try:
                ctx.close(); browser.close(); pw.stop()
            except Exception:
                pass

        print(f"[DEBUG] macaroni_kid: details={len(detail_items)}")
        return detail_items

    def normalize(self, items: list[RawItem]) -> List[NormalizedEvent]:
        out: list[NormalizedEvent] = []
        for it in items:
            html = it.payload.get("html")
            if not html:
                # should rarely happen; we rely on rendered pages
                continue

            candidates = _parse_jsonld(html, it.source_url)
            if not candidates:
                candidates = _parse_html_light(html, it.source_url)

            for ev in candidates:
                if not ev.get("title"):
                    continue
                start_iso = ev.get("start_dt")
                uid = hashlib.sha1(f"{it.source_url}|{ev['title']}|{start_iso}".encode()).hexdigest()[:20]
                data = {
                    "uid": uid,
                    "source_url": it.source_url,
                    "title": ev["title"],
                    "description": _clean_text(ev.get("description") or ""),
                    "category": "general",
                    "age_min": None,
                    "age_max": None,
                    "start_dt": start_iso,
                    "end_dt": ev.get("end_dt"),
                    "tz": "America/New_York",
                    "venue_name": ev.get("venue_name"),
                    "address": ev.get("address"),
                    "lat": None,
                    "lng": None,
                    "cost_min": None,
                    "cost_max": None,
                    "registration_url": ev.get("registration_url") or it.source_url,
                    "tags": {},
                }
                out.append(NormalizedEvent(uid=uid, data=data))
        return out
