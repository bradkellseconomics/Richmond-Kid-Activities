from __future__ import annotations
import argparse, os
from .pipeline import harvest, select_and_score, select_grouped_all, init_db, window_next_week
from .db import SessionLocal
from .models import Event, Source
from sqlalchemy import select
from .sources import ensure_sources, DEFAULT_SOURCES
from .emailer import render_newsletter, send_email


def main():
    ap = argparse.ArgumentParser("rk")
    ap.add_argument("cmd", choices=[
        "init", "harvest", "weekly",
        "preview", "preview-existing",
        "preview-list", "preview-list-existing",
        "preview-dummy", "list",
        "sources-sync", "sources-prune",
        "mk-debug", "email-test"
    ], help="Run a pipeline action")
    args = ap.parse_args()

    if args.cmd == "init":
        init_db(); ensure_sources(); print("DB initialized and sources added.")
    elif args.cmd == "harvest":
        ensure_sources(); n = harvest(); print(f"Harvested {n} events")
    elif args.cmd == "weekly":
        ensure_sources(); harvest()
        top, more = select_and_score()
        from datetime import timedelta
        start, end = window_next_week("sat")
        end_disp = end - timedelta(days=1)
        week_range = f"{start.strftime('%a %b %d')} - {end_disp.strftime('%a %b %d')}"
        html, text = render_newsletter(top, more, week_range=week_range)
        send_email("Richmond Kids: Next Week", html, text)
        print(f"Sent newsletter. Top={len(top)}, More={len(more)}")
    elif args.cmd == "preview":
        # Harvest, render, and write to files locally without sending email
        ensure_sources(); harvest()
        top, more = select_and_score()
        from datetime import timedelta
        start, end = window_next_week("sat")
        end_disp = end - timedelta(days=1)
        week_range = f"{start.strftime('%a %b %d')} - {end_disp.strftime('%a %b %d')}"
        html, text = render_newsletter(top, more, week_range=week_range)
        out_dir = os.path.join(os.getcwd(), "newsletter_output")
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, "newsletter_preview.html")
        txt_path = os.path.join(out_dir, "newsletter_preview.txt")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        # Also write full ranked selection (post-dedupe/group)
        try:
            import json
            from .emailer import _fmt_dt
            all_grouped = select_grouped_all()
            full_json = os.path.join(out_dir, "selection_full.json")
            with open(full_json, "w", encoding="utf-8") as f:
                # Convert any datetime fields (e.g., first_seen/last_seen) to strings
                json.dump(all_grouped, f, ensure_ascii=False, indent=2, default=str)
            full_txt = os.path.join(out_dir, "selection_full.txt")
            with open(full_txt, "w", encoding="utf-8") as f:
                for idx, e in enumerate(all_grouped, 1):
                    line = f"{idx:2d}. {e.get('title','')} — {_fmt_dt(e.get('start_dt',''))}"
                    if e.get('venue_name'): line += f" at {e['venue_name']}"
                    if e.get('source_name'): line += f" • {e['source_name']}"
                    line += f" | score={e.get('_score')}"
                    f.write(line + "\n")
                    if e.get('occurrence_summary'):
                        f.write(f"    {e['occurrence_summary']}\n")
            print(f"Wrote preview files:\n- {html_path}\n- {txt_path}\n- {full_json}\n- {full_txt}")
        except Exception as e:
            print(f"[WARN] Could not write selection_full files: {e}")
    elif args.cmd == "preview-existing":
        # Use existing DB contents; do not harvest
        top, more = select_and_score()
        from datetime import timedelta
        start, end = window_next_week("sat")
        end_disp = end - timedelta(days=1)
        week_range = f"{start.strftime('%a %b %d')} - {end_disp.strftime('%a %b %d')}"
        html, text = render_newsletter(top, more, week_range=week_range)
        out_dir = os.path.join(os.getcwd(), "newsletter_output")
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, "newsletter_preview.html")
        txt_path = os.path.join(out_dir, "newsletter_preview.txt")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        # Also write full ranked selection (post-dedupe/group)
        try:
            import json
            from .emailer import _fmt_dt
            all_grouped = select_grouped_all()
            full_json = os.path.join(out_dir, "selection_full.json")
            with open(full_json, "w", encoding="utf-8") as f:
                json.dump(all_grouped, f, ensure_ascii=False, indent=2, default=str)
            full_txt = os.path.join(out_dir, "selection_full.txt")
            with open(full_txt, "w", encoding="utf-8") as f:
                for idx, e in enumerate(all_grouped, 1):
                    line = f"{idx:2d}. {e.get('title','')} — {_fmt_dt(e.get('start_dt',''))}"
                    if e.get('venue_name'): line += f" at {e['venue_name']}"
                    if e.get('source_name'): line += f" • {e['source_name']}"
                    line += f" | score={e.get('_score')}"
                    f.write(line + "\n")
                    if e.get('occurrence_summary'):
                        f.write(f"    {e['occurrence_summary']}\n")
            print(f"Wrote preview files (existing DB):\n- {html_path}\n- {txt_path}\n- {full_json}\n- {full_txt}")
        except Exception as e:
            print(f"[WARN] Could not write selection_full files: {e}")
    elif args.cmd == "preview-dummy":
        # Generate a dummy preview without network/DB
        top = [
            {
                "uid": "dummy1",
                "source_url": "https://example.org/a",
                "title": "Storytime at the Library",
                "description": "Songs, stories, and fun for ages 3–6.",
                "category": "library",
                "age_min": 3,
                "age_max": 6,
                "start_dt": "2025-07-12T10:00:00-04:00",
                "end_dt": "2025-07-12T11:00:00-04:00",
                "tz": "America/New_York",
                "venue_name": "Main Branch",
                "address": "101 Main St, Richmond, VA",
                "lat": None,
                "lng": None,
                "cost_min": 0,
                "cost_max": 0,
                "registration_url": "https://example.org/a",
                "tags": {},
            },
            {
                "uid": "dummy2",
                "source_url": "https://example.org/b",
                "title": "Kids Science Workshop",
                "description": "Hands-on experiments for ages 7–12.",
                "category": "science",
                "age_min": 7,
                "age_max": 12,
                "start_dt": "2025-07-13T14:00:00-04:00",
                "end_dt": "2025-07-13T15:30:00-04:00",
                "tz": "America/New_York",
                "venue_name": "Science Center",
                "address": "200 Museum Rd, Richmond, VA",
                "lat": None,
                "lng": None,
                "cost_min": 10,
                "cost_max": 10,
                "registration_url": "https://example.org/b",
                "tags": {},
            },
        ]
        more = [
            {
                "uid": "dummy3",
                "source_url": "https://example.org/c",
                "title": "Family Garden Walk",
                "description": "Guided tour through the summer blooms.",
                "category": "nature",
                "age_min": None,
                "age_max": None,
                "start_dt": "2025-07-15T09:00:00-04:00",
                "end_dt": None,
                "tz": "America/New_York",
                "venue_name": "Botanical Garden",
                "address": "1800 Garden Pkwy, Richmond, VA",
                "lat": None,
                "lng": None,
                "cost_min": 0,
                "cost_max": 0,
                "registration_url": "https://example.org/c",
                "tags": {},
            }
        ]
        html, text = render_newsletter(top, more)
        out_dir = os.path.join(os.getcwd(), "newsletter_output")
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, "newsletter_preview.html")
        txt_path = os.path.join(out_dir, "newsletter_preview.txt")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote preview files (dummy data):\n- {html_path}\n- {txt_path}")
        print(f"Wrote preview files (dummy data):\n- {html_path}\n- {txt_path}")
    elif args.cmd == "preview-list":
        # Show which events were selected for the upcoming newsletter (fresh harvest)
        ensure_sources(); harvest()
        top, more = select_and_score()
        print(f"Selected events: top={len(top)}, more={len(more)}")
        if top:
            print("Top Picks:")
            for e in top:
                src = e.get('source_name') or ''
                print(f"- {e['title']} | {e['start_dt']} | {e.get('venue_name') or ''} | {src} | score={e.get('_score')}")
        if more:
            print("More:")
            for e in more:
                src = e.get('source_name') or ''
                print(f"- {e['title']} | {e['start_dt']} | {e.get('venue_name') or ''} | {src} | score={e.get('_score')}")
    elif args.cmd == "preview-list-existing":
        # Show which events were selected using current DB only (no harvest)
        top, more = select_and_score()
        print(f"Selected events (existing DB): top={len(top)}, more={len(more)}")
        if top:
            print("Top Picks:")
            for e in top:
                src = e.get('source_name') or ''
                print(f"- {e['title']} | {e['start_dt']} | {e.get('venue_name') or ''} | {src} | score={e.get('_score')}")
        if more:
            print("More:")
            for e in more:
                src = e.get('source_name') or ''
                print(f"- {e['title']} | {e['start_dt']} | {e.get('venue_name') or ''} | {src} | score={e.get('_score')}")
    elif args.cmd == "mk-debug":
        # Debug Macaroni KID extraction without touching DB
        from .extractors.macaroni_kid import MacaroniKidExtractor
        srcs = [s for s in DEFAULT_SOURCES if s["kind"] == "macaronikid"]
        if not srcs:
            print("No Macaroni KID source configured in DEFAULT_SOURCES")
            return
        url = srcs[0]["url"]
        ex = MacaroniKidExtractor()
        print(f"[DEBUG] Discovering from {url}")
        items = ex.discover(url)
        print(f"[DEBUG] Discovered {len(items)} event links")
        sample = items[:10]
        if sample:
            print("[DEBUG] Sample links:")
            for it in sample:
                print(f" - {it.source_url}")
        print("[DEBUG] Normalizing first 5...")
        norm = ex.normalize(items[:5])
        print(f"[DEBUG] Normalized {len(norm)} items")
        for n in norm:
            d = n.data
            print(f" - {d['title']} | {d.get('start_dt')} | {d.get('venue_name') or ''}")
    elif args.cmd == "email-test":
        # Send a simple test email to verify SMTP and recipients
        html = """
        <html><body>
        <h3>Richmond Kids — SMTP Test</h3>
        <p>If you received this, SMTP credentials and recipient list are working.</p>
        <ul>
          <li>From: {from_email}</li>
          <li>To: {to_emails}</li>
          <li>Host: {host}:{port}</li>
        </ul>
        </body></html>
        """.format(from_email=CFG.from_email, to_emails=", ".join(CFG.to_emails), host=CFG.smtp_host, port=CFG.smtp_port)
        text = (
            "Richmond Kids — SMTP Test\n\n"
            f"From: {CFG.from_email}\n"
            f"To: {', '.join(CFG.to_emails)}\n"
            f"Host: {CFG.smtp_host}:{CFG.smtp_port}\n"
        )
        send_email("RK Test Email — SMTP OK", html, text)
        print("Sent test email. Check your inbox (and Spam).")
    elif args.cmd == "sources-sync":
        ensure_sources()
        print("Sources synchronized to defaults (updated/added as needed).")
    elif args.cmd == "sources-prune":
        # Deactivate any sources not present in DEFAULT_SOURCES (by name)
        keep_names = {s["name"] for s in DEFAULT_SOURCES}
        with SessionLocal() as s:
            rows = list(s.scalars(select(Source)))
            pruned = 0
            for r in rows:
                if r.name not in keep_names and r.active == 1:
                    r.active = 0
                    s.add(r)
                    pruned += 1
            s.commit()
        print(f"Pruned {pruned} sources (set active=0) not in defaults.")
    elif args.cmd == "list":
        # Show a quick summary of harvested events in DB
        with SessionLocal() as s:
            rows = list(s.scalars(select(Event)))
        print(f"Events in DB: {len(rows)}")
        for e in rows[:10]:
            print(f"- {e.title} | {e.start_dt} | {e.venue_name or ''}")
