# macaroni_kid.py
from __future__ import annotations
import csv
import hashlib
import os
import re
import time
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import extruct
from dateutil import parser as dtp
from dateutil import tz as dttz
from selectolax.parser import HTMLParser
from w3lib.html import get_base_url
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
LOCAL_TZ = dttz.gettz("America/New_York")

def dprint(*args):
    if DEBUG:
        print("[DEBUG]", *args)

# ---------------- paths ----------------
def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True)
    return p

P_DEBUG = _ensure_dir(os.path.join("data", "debug", "macaroni_kid"))
P_PAGES = _ensure_dir(os.path.join(P_DEBUG, "pages"))
P_NEWS  = _ensure_dir("newsletter_output")
P_MACKID_DEBUG = os.path.join(P_NEWS, "mackid_debug")

# --------------- sanitizers ---------------
SCRIPT_TAG_PAT   = re.compile(r"<script\b[^>]*>[\s\S]*?</script>", re.I)
STYLE_TAG_PAT    = re.compile(r"<style\b[^>]*>[\s\S]*?</style>", re.I)
QS_LISTENER_PAT  = re.compile(r"document\.querySelector\([^)]+\)\.addEventListener\([^)]*\)\s*\{[\s\S]*?\}\s*;?", re.I)
SPONSOR_URL_PAT  = re.compile(r"https?://sponsors\.macaronikid\.com[:/\w\-\.\?\=&%]*", re.I)

def _clean_text(s: str) -> str:
    if not s:
        return ""
    s = SCRIPT_TAG_PAT.sub(" ", s)
    s = STYLE_TAG_PAT.sub(" ", s)
    s = QS_LISTENER_PAT.sub(" ", s)
    s = SPONSOR_URL_PAT.sub(" ", s)
    s = html_mod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _extract_visible_text(html_str: str, selector: str | None = None, max_len: int = 4000) -> str:
    try:
        doc = HTMLParser(html_str)
        node = doc.css_first(selector) if selector else (doc.body or doc.root)
        if not node:
            return ""
        for n in node.css("script, style, noscript"):
            n.decompose()
        txt = node.text(separator=" ").strip()
        return _clean_text(txt)[:max_len]
    except Exception:
        return ""

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

def _meta_desc(html: str) -> str | None:
    try:
        doc = HTMLParser(html)
        m = doc.css_first('meta[property="og:description"], meta[name="description"]')
        if m and m.attributes.get("content"):
            return m.attributes["content"].strip()
    except Exception:
        pass
    return None

# ------------ date/time parsing ------------
# Month Day[, Year] HH:MM am/pm [– HH:MM am/pm]
TIME_RE = re.compile(
    r"""
    (?P<dow>Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\.?,?\s*
    (?P<month>January|February|March|April|May|June|July|August|September|October|November|December)
    \s+(?P<day>\d{1,2})(?:,\s*(?P<year>\d{4}))?
    [^0-9A-Za-z]+
    (?P<hour1>\d{1,2})\s*:\s*(?P<min1>\d{2})\s*(?P<ampm1>am|pm|AM|PM)
    (?:\s*[-–]\s*
        (?P<hour2>\d{1,2})\s*:\s*(?P<min2>\d{2})\s*(?P<ampm2>am|pm|AM|PM)
    )?
    """,
    re.VERBOSE,
)

def _parse_times_from_text(body_text: str, default_year: int | None = None) -> tuple[Optional[str], Optional[str]]:
    m = TIME_RE.search(body_text or "")
    if not m:
        return None, None
    g = m.groupdict()
    from datetime import datetime as _dt
    year = int(g["year"]) if g["year"] else (default_year or _dt.now(LOCAL_TZ).year)
    date_str = f"{g['month']} {g['day']}, {year}"

    def _build(h, mi, ap): return f"{date_str} {h}:{mi} {ap}"

    start_s = _build(g["hour1"], g["min1"], g["ampm1"])
    end_s   = _build(g["hour2"], g["min2"], g["ampm2"]) if g["hour2"] else None
    try:
        s_dt = dtp.parse(start_s); e_dt = dtp.parse(end_s) if end_s else None
        if s_dt.tzinfo is None: s_dt = s_dt.replace(tzinfo=LOCAL_TZ)
        if e_dt and e_dt.tzinfo is None: e_dt = e_dt.replace(tzinfo=LOCAL_TZ)
        return s_dt.isoformat(), (e_dt.isoformat() if e_dt else None)
    except Exception:
        return None, None

def _find_times_from_html(html: str) -> tuple[Optional[str], Optional[str]]:
    # Prefer explicit time tags
    try:
        doc = HTMLParser(html)
        t_start = doc.css_first("time[datetime]")
        t_end   = doc.css_first("time[itemprop='endDate'], time[datetime]:nth-child(2)")
        s_iso = _to_local_iso(t_start.attributes.get("datetime")) if t_start and t_start.attributes.get("datetime") else None
        e_iso = _to_local_iso(t_end.attributes.get("datetime")) if t_end and t_end.attributes.get("datetime") else None
        if s_iso:
            return s_iso, e_iso
    except Exception:
        pass
    # Fallback: parse visible text
    text = _extract_visible_text(html, selector=".event, .event-content, article, main, .content, body")
    return _parse_times_from_text(text)

# ------------ venue/address helpers ------------
def _compose_postal_address(addr: dict) -> str:
    parts = [
        (addr.get("streetAddress") or "").strip(),
        " ".join(
            x for x in [(addr.get("addressLocality") or "").strip(),
                        (addr.get("addressRegion") or "").strip()]
            if x
        ),
        (addr.get("postalCode") or "").strip(),
        (addr.get("addressCountry") or "").strip(),
    ]
    return ", ".join([re.sub(r"\s+", " ", p).strip() for p in parts if p.strip()])

def _extract_venue_address_from_html(html: str) -> tuple[Optional[str], Optional[str]]:
    try:
        doc = HTMLParser(html)

        # maps links often include readable address text
        maps_link = doc.css_first("a[href*='google.com/maps'], a[href*='maps.apple.com']")
        maps_text = _clean_text(maps_link.text(separator=" ").strip()) if maps_link else None

        venue_txt = None
        addr_txt  = None

        # "Where:" lines in details
        for li in doc.css("li, .event-details li, .details li"):
            t = _clean_text(li.text(separator=" ").strip())
            if t.lower().startswith("where"):
                t2 = re.sub(r"^\s*where\s*:?\s*", "", t, flags=re.I).strip()
                if maps_text:
                    # naive split: first comma-segment looks like venue
                    parts = maps_text.split(",")
                    if len(parts) >= 2:
                        venue_txt = parts[0].strip() or venue_txt
                    addr_txt = maps_text
                else:
                    if " - " in t2:
                        venue_txt, addr_txt = t2.split(" - ", 1)
                    elif ", " in t2:
                        parts = t2.split(", ")
                        if len(parts) >= 3:
                            venue_txt = parts[0]
                            addr_txt  = ", ".join(parts[1:])
                        else:
                            addr_txt = t2
                    else:
                        addr_txt = t2
                break

        # itemprop hints
        if not venue_txt:
            loc_name = doc.css_first('[itemprop="location"] [itemprop="name"], [itemprop="locationName"]')
            if loc_name:
                venue_txt = _clean_text(loc_name.text(separator=" ").strip()) or None
        if not addr_txt:
            addr_block = doc.css_first('[itemprop="address"], .address, .venue-address')
            if addr_block:
                addr_txt = _clean_text(addr_block.text(separator=" ").strip()) or None

        if not addr_txt and maps_text:
            addr_txt = maps_text

        venue_txt = _clean_text(venue_txt or "") or None
        addr_txt  = _clean_text(addr_txt or "") or None
        return venue_txt, addr_txt
    except Exception:
        return None, None

# ------------ JSON-LD / HTML candidate builders ------------
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
            end_iso   = _to_local_iso(o.get("endDate"))
            desc      = _clean_text((o.get("description") or "").strip())
            if not start_iso or not end_iso:
                s2, e2 = _find_times_from_html(html)
                start_iso = start_iso or s2
                end_iso   = end_iso or e2
            if not desc:
                desc = _clean_text(_meta_desc(html) or "")

            venue = None
            address_str = None
            loc = o.get("location") or {}
            if isinstance(loc, dict):
                venue = _clean_text((loc.get("name") or "").strip()) or None
                addr = loc.get("address")
                if isinstance(addr, dict):
                    address_str = _compose_postal_address(addr) or None
                elif isinstance(addr, str):
                    address_str = _clean_text(addr) or None

            out.append({
                "title": title,
                "description": desc,
                "start_dt": start_iso,
                "end_dt": end_iso,
                "venue_name": venue,
                "address": address_str,
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
    s_iso, e_iso = _find_times_from_html(html)
    desc = _meta_desc(html) or _extract_visible_text(html, selector=".event, .event-content, article, main, .content")
    desc = _clean_text(desc)
    # venue/address fallback here only as a hint; final backfill happens in normalize()
    return [{
        "title": title,
        "description": desc,
        "start_dt": s_iso,
        "end_dt": e_iso,
        "venue_name": None,
        "address": None,
        "registration_url": page_url,
    }]

# ------------ playwright context ------------
def _playwright_context():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        dprint(f"playwright import failed -> {e}")
        return None, None, None
    pw = None; browser = None; ctx = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=UA["User-Agent"],
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
    except Exception as e:
        dprint(f"playwright startup failed -> {e}")
        try:
            if ctx: ctx.close()
            if browser: browser.close()
            if pw: pw.stop()
        except Exception:
            pass
        return None, None, None
    return pw, browser, ctx

def _slug_from_url(u: str) -> str:
    path = urlparse(u).path.rstrip("/")
    last = path.split("/")[-1] or "event"
    prev = path.split("/")[-2] if len(path.split("/")) >= 2 else ""
    base = (prev + "_" + last) if prev and prev.isalnum() else last
    return re.sub(r"[^a-zA-Z0-9\-_]+", "_", base)[:80]

# --------------- Extractor ---------------
class MacaroniKidExtractor(Extractor):
    """
    JS-render the Macaroni KID list page, collect /events/<slug> links,
    fetch each event, parse start/end + venue/address, and normalize.
    Stores events even if start_dt is None; dumps CSV and a weak-event log.
    """
    kind = "macaronikid"

    def discover(self, source_url: str) -> List[RawItem]:
        # RK_LIMIT lets you clamp for test runs (e.g., $env:RK_LIMIT="10")
        try:
            rk_limit = int(os.getenv("RK_LIMIT", "0"))
        except Exception:
            rk_limit = 0

        pw, browser, ctx = _playwright_context()
        detail_items: list[RawItem] = []

        if pw is None:
            dprint("Playwright unavailable; static fallback will likely miss events.")
            try:
                import requests
                r = requests.get(source_url, timeout=25, headers=UA)
                r.raise_for_status()
                doc = HTMLParser(r.text)
                anchors = doc.css("a")
                links = sorted({
                    urljoin(source_url, a.attributes.get("href", ""))
                    for a in anchors
                    if a.attributes.get("href")
                    and "/events/" in a.attributes.get("href", "")
                    and "/events/calendar" not in a.attributes["href"]
                    and "/events/submit" not in a.attributes["href"]
                })
            except Exception as e:
                print(f"[WARN] Macaroni KID static fetch failed: {e}")
                links = []
            if rk_limit:
                links = links[:rk_limit]
            for ev_url in links:
                detail_items.append(RawItem(source_url=ev_url, payload={"html": None}))
            print(f"[DEBUG] macaroni_kid(static): details={len(detail_items)}")
            return detail_items

        # Playwright path
        try:
            p = ctx.new_page()
            p.set_default_timeout(20000)
            dprint(f"Go to {source_url}")
            p.goto(source_url, wait_until="domcontentloaded")
            try:
                p.wait_for_load_state("networkidle")
            except Exception:
                pass
            p.wait_for_timeout(800)
            if DEBUG:
                _ensure_dir(P_MACKID_DEBUG)

            # Attempt to clear consent/overlay prompts
            try:
                for txt in ["Accept", "I Agree", "Agree", "OK"]:
                    try:
                        loc = p.locator(f'button:has-text("{txt}")')
                        if loc.count() > 0:
                            loc.first.click(timeout=1500)
                            p.wait_for_timeout(350)
                    except Exception:
                        pass
            except Exception:
                pass

            # Click weekday/date tabs to hydrate content
            tabs = []
            try:
                tabs = p.locator("a, button").filter(has_text=r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}$").all()
            except Exception:
                tabs = []
            if not tabs:
                try:
                    tabs = p.locator("a[href^='#']").all()
                except Exception:
                    tabs = []
            for t in tabs[:7]:
                try:
                    t.click()
                    p.wait_for_timeout(450)
                    p.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    p.wait_for_timeout(450)
                except Exception:
                    pass

            # Click weekday tabs to hydrate lists
            try:
                tabs = p.locator("a, button").filter(has_text=r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b").all()
                for t in tabs[:7]:
                    try:
                        t.click()
                        p.wait_for_timeout(350)
                    except Exception:
                        pass
            except Exception:
                pass

            # Scroll to trigger lazy load
            for _ in range(6):
                p.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                p.wait_for_timeout(650)

            # Collect event links
            hrefs = p.eval_on_selector_all(
                "a[href*='/events/']",
                "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
            )
            links = sorted({
                urljoin(p.url, h) for h in hrefs
                if "/events/calendar" not in h and "/events/submit" not in h
            })
            if len(links) == 0:
                try:
                    _ensure_dir(P_MACKID_DEBUG)
                    try:
                        p.screenshot(path=os.path.join(P_MACKID_DEBUG, "list.png"), full_page=True)
                    except Exception:
                        pass
                    try:
                        html = p.content()
                        with open(os.path.join(P_MACKID_DEBUG, "list.html"), "w", encoding="utf-8") as f:
                            f.write(html)
                    except Exception:
                        pass
                    log_lines = []
                    try:
                        title = p.title()
                    except Exception:
                        title = ""
                    try:
                        body_txt = p.evaluate("() => (document.body && document.body.innerText) ? document.body.innerText : ''")
                    except Exception:
                        body_txt = ""
                    body_head = re.sub(r"\\s+", " ", (body_txt or ""))[:500]
                    try:
                        counts = {
                            "event_links": p.locator("a[href*='/events/']").count(),
                            "events_text": p.locator("text=EVENTS").count(),
                            "subscribe_text": p.locator("text=Subscribe").count(),
                        }
                    except Exception:
                        counts = {}
                    log_lines.append(f"url: {p.url}")
                    log_lines.append(f"title: {title}")
                    log_lines.append(f"body_head: {body_head}")
                    if counts:
                        for k, v in counts.items():
                            log_lines.append(f"count:{k}={v}")
                    try:
                        with open(os.path.join(P_MACKID_DEBUG, "list_head.txt"), "w", encoding="utf-8") as f:
                            for line in log_lines:
                                f.write(line + "\n")
                    except Exception:
                        pass
                    dprint("No links found; wrote mackid_debug artifacts")
                    if DEBUG:
                        dprint("title:", title)
                        dprint("body head:", body_head)
                        if counts:
                            dprint("counts:", counts)
                except Exception:
                    pass
            if rk_limit:
                links = links[:rk_limit]
            dprint(f"found {len(links)} event links")

            # Visit each event page and stash rendered HTML
            for i, ev_url in enumerate(links):
                try:
                    dp = ctx.new_page()
                    dp.set_default_timeout(20000)
                    dp.goto(ev_url, wait_until="domcontentloaded")
                    dp.wait_for_timeout(850)
                    html = dp.content()
                    # Save a copy for human inspection
                    try:
                        fname = os.path.join(P_PAGES, _slug_from_url(ev_url) + ".html")
                        with open(fname, "w", encoding="utf-8") as f:
                            f.write(html)
                    except Exception:
                        pass
                    detail_items.append(RawItem(source_url=ev_url, payload={"html": html}))
                    dp.close()
                    if DEBUG and (i % 25 == 0):
                        print(f"[DEBUG] captured {i+1}/{len(links)} -> {ev_url}")
                    time.sleep(0.15)
                except Exception as e:
                    print(f"[WARN] MacaroniKid event fetch failed: {ev_url} -> {e}")
        finally:
            try:
                p.close()
            except Exception:
                pass
            try:
                ctx.close(); browser.close(); pw.stop()
            except Exception:
                pass

        print(f"[DEBUG] macaroni_kid: details={len(detail_items)}")
        return detail_items

    def normalize(self, items: list[RawItem]) -> List[NormalizedEvent]:
        out: list[NormalizedEvent] = []
        weak_events: list[str] = []

        try:
            import requests
        except Exception:
            requests = None  # type: ignore

        for it in items:
            html = it.payload.get("html")
            if not html and requests:
                try:
                    r = requests.get(it.source_url, timeout=25, headers=UA)
                    r.raise_for_status()
                    html = r.text
                except Exception as e:
                    print(f"[WARN] fallback GET failed: {it.source_url} -> {e}")
                    html = ""

            if not html:
                title = it.source_url.split("/")[-1].replace("-", " ").title()
                start_iso = None
                uid = hashlib.sha1(f"{it.source_url}|{title}|{start_iso}".encode()).hexdigest()[:20]
                out.append(NormalizedEvent(uid=uid, data={
                    "uid": uid, "source_url": it.source_url, "title": title,
                    "description": "", "category": "general",
                    "age_min": None, "age_max": None,
                    "start_dt": None, "end_dt": None, "tz": "America/New_York",
                    "venue_name": None, "address": None,
                    "lat": None, "lng": None, "cost_min": None, "cost_max": None,
                    "registration_url": it.source_url, "tags": {},
                }))
                weak_events.append(it.source_url + " | (no HTML)")
                continue

            candidates = _parse_jsonld(html, it.source_url)
            if not candidates:
                candidates = _parse_html_light(html, it.source_url)

            if not candidates:
                title = it.source_url.split("/")[-1].replace("-", " ").title()
                start_iso = None
                uid = hashlib.sha1(f"{it.source_url}|{title}|{start_iso}".encode()).hexdigest()[:20]
                out.append(NormalizedEvent(uid=uid, data={
                    "uid": uid, "source_url": it.source_url, "title": title,
                    "description": "", "category": "general",
                    "age_min": None, "age_max": None,
                    "start_dt": None, "end_dt": None, "tz": "America/New_York",
                    "venue_name": None, "address": None,
                    "lat": None, "lng": None, "cost_min": None, "cost_max": None,
                    "registration_url": it.source_url, "tags": {},
                }))
                weak_events.append(it.source_url + " | (no parsed candidates)")
                continue

            for ev in candidates:
                title = ev.get("title") or ""
                start_iso = ev.get("start_dt")

                # Backfill venue/address if JSON-LD didn’t include them
                venue_name = ev.get("venue_name")
                address    = ev.get("address")
                if not (venue_name and address):
                    v2, a2 = _extract_venue_address_from_html(html)
                    venue_name = venue_name or v2
                    address    = address or a2

                uid = hashlib.sha1(f"{it.source_url}|{title}|{start_iso}".encode()).hexdigest()[:20]
                data = {
                    "uid": uid,
                    "source_url": it.source_url,
                    "title": title,
                    "description": _clean_text(ev.get("description") or ""),
                    "category": "general",
                    "age_min": None, "age_max": None,
                    "start_dt": start_iso,
                    "end_dt": ev.get("end_dt"),
                    "tz": "America/New_York",
                    "venue_name": venue_name,
                    "address": address,
                    "lat": None, "lng": None,
                    "cost_min": None, "cost_max": None,
                    "registration_url": ev.get("registration_url") or it.source_url,
                    "tags": {},
                }
                if start_iso is None:
                    weak_events.append(f"{it.source_url} | missing start_dt | title={title[:80]}")
                out.append(NormalizedEvent(uid=uid, data=data))

        # Snapshot CSV for inspection
        try:
            csv_path = os.path.join(P_NEWS, "last_normalized.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["title", "start_dt", "end_dt", "venue", "address", "url", "source"])
                for e in out:
                    d = e.data
                    w.writerow([
                        d.get("title") or "",
                        d.get("start_dt") or "",
                        d.get("end_dt") or "",
                        d.get("venue_name") or "",
                        d.get("address") or "",
                        d.get("registration_url") or d.get("source_url") or "",
                        "Macaroni KID Richmond",
                    ])
            if DEBUG:
                print(f"[DEBUG] wrote CSV -> {csv_path}")
        except Exception as e:
            print(f"[WARN] CSV dump failed: {e}")

        # Weak events log
        try:
            log_path = os.path.join(P_NEWS, "last_skips.log")
            with open(log_path, "w", encoding="utf-8") as f:
                for line in weak_events:
                    f.write(line + "\n")
            if DEBUG:
                print(f"[DEBUG] wrote weak-event log -> {log_path}")
        except Exception as e:
            print(f"[WARN] skip log write failed: {e}")

        return out
