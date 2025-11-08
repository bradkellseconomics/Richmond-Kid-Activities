# test.py — Macaroni KID probe with reliable date+time extraction
import time, re, html
from urllib.parse import urljoin
from datetime import datetime
from dateutil import parser as dtp
from dateutil import tz as dttz
from playwright.sync_api import sync_playwright

BASE_URL = "https://richmond.macaronikid.com/events"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537"
ET = dttz.gettz("America/New_York")

def clean(s): 
    s = html.unescape(s or "")
    return re.sub(r"\s+", " ", s).strip()

# Regex that captures: Month Day, [Year] HH:MM am/pm [– HH:MM am/pm]
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

def to_iso_local(dt_obj):
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=ET)
    else:
        dt_obj = dt_obj.astimezone(ET)
    return dt_obj.isoformat()

def parse_from_text(body_text: str, default_year: int | None = None):
    m = TIME_RE.search(body_text or "")
    if not m:
        return None, None
    g = m.groupdict()
    year = int(g["year"]) if g["year"] else (default_year or datetime.now(ET).year)
    date_str = f"{g['month']} {g['day']}, {year}"

    def build(h, mi, ap):
        return f"{date_str} {h}:{mi} {ap}"

    start_s = build(g["hour1"], g["min1"], g["ampm1"])
    end_s   = build(g["hour2"], g["min2"], g["ampm2"]) if g["hour2"] else None
    try:
        s_dt = dtp.parse(start_s)
        e_dt = dtp.parse(end_s) if end_s else None
        return to_iso_local(s_dt), (to_iso_local(e_dt) if e_dt else None)
    except Exception:
        return None, None

def extract_times(dp):
    # 1) Prefer explicit <time datetime="...">
    times = dp.locator("time[datetime]").all()
    start_iso = end_iso = None
    if times:
        try:
            start_iso = to_iso_local(dtp.parse(times[0].get_attribute("datetime")))
            if len(times) > 1:
                end_iso = to_iso_local(dtp.parse(times[1].get_attribute("datetime")))
            if start_iso:
                return start_iso, end_iso
        except Exception:
            pass

    # 2) Fallback: parse from visible text
    #   Scope to event content areas first; fall back to body
    for sel in [".event, .event-content, article, main, .content", "body"]:
        try:
            node = dp.locator(sel)
            if node.count():
                txt = clean(node.first.inner_text()[:8000])
                s,e = parse_from_text(txt)
                if s:
                    return s,e
        except Exception:
            continue
    return None, None

def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900})
        page = ctx.new_page()

        print(f"Loading: {BASE_URL}")
        page.goto(BASE_URL, wait_until="domcontentloaded")
        time.sleep(1.2)

        # Click weekday tabs to hydrate lists
        tabs = page.locator("a, button").filter(has_text=r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b").all()
        for t in tabs[:7]:
            try:
                t.click(); time.sleep(0.35)
            except: pass

        # Scroll to trigger lazy load
        for _ in range(6):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.6)

        # Collect event links
        hrefs = page.eval_on_selector_all(
            "a[href*='/events/']",
            "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
        )
        links = sorted({urljoin(page.url, h) for h in hrefs
                        if "/events/calendar" not in h and "/events/submit" not in h})
        print(f"✅ Found {len(links)} event links")
        print("Sample:", links[:5])

        # Fetch a few details
        for ev_url in links[:5]:
            dp = ctx.new_page()
            dp.goto(ev_url, wait_until="domcontentloaded"); time.sleep(0.7)
            title = clean(dp.title())
            body = clean(dp.locator("body").inner_text()[:3000])
            start_iso, end_iso = extract_times(dp)

            print("\n--- EVENT ---")
            print("URL:", ev_url)
            print("TITLE:", title or "(missing)")
            print("START:", start_iso or "(no start parsed)")
            print("END  :", end_iso or "(no end parsed)")
            print("DESC :", body[:200], "...")
            dp.close()

        browser.close()

if __name__ == "__main__":
    main()
