# play_mac_kid_probe.py
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

URL = "https://richmond.macaronikid.com/events"

def main():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = b.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 rk-bot/1.0"
        ))
        p = ctx.new_page()
        p.set_default_timeout(20000)
        p.goto(URL, wait_until="domcontentloaded")
        p.wait_for_timeout(1200)

        # Click visible day tabs once (helps hydrate lists)
        try:
            tabs = p.locator("a, button").filter(has_text=r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b").all()
            for t in tabs[:7]:
                t.click()
                p.wait_for_timeout(300)
        except Exception:
            pass

        # Scroll a bit to trigger lazy-load
        for _ in range(4):
            p.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            p.wait_for_timeout(500)

        # Collect event links now that DOM is hydrated
        hrefs = p.eval_on_selector_all(
            "a[href*='/events/']",
            "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
        )
        links = sorted({ urljoin(p.url, h) for h in hrefs
                         if "/events/calendar" not in h and "/events/submit" not in h })

        print(f"FOUND {len(links)} event links")
        for h in links[:25]:
            print(" -", h)

        # Optional: grab one detail page HTML to confirm we can parse it
        if links:
            dp = ctx.new_page()
            dp.goto(links[0], wait_until="domcontentloaded")
            dp.wait_for_timeout(800)
            html = dp.content()
            print(f"\nDetail sample length: {len(html)}")
            dp.close()

        p.close(); ctx.close(); b.close()

if __name__ == "__main__":
    main()
