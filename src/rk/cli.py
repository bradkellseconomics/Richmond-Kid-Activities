from __future__ import annotations
import argparse, os
from .pipeline import harvest, select_and_score, init_db
from .sources import ensure_sources
from .emailer import render_newsletter, send_email


def main():
    ap = argparse.ArgumentParser("rk")
    ap.add_argument("cmd", choices=["init", "harvest", "weekly", "preview"], help="Run a pipeline action")
    args = ap.parse_args()

    if args.cmd == "init":
        init_db(); ensure_sources(); print("DB initialized and sources added.")
    elif args.cmd == "harvest":
        ensure_sources(); n = harvest(); print(f"Harvested {n} events")
    elif args.cmd == "weekly":
        ensure_sources(); harvest()
        top, more = select_and_score()
        html, text = render_newsletter(top, more)
        send_email("Richmond Kids: Next Week", html, text)
        print(f"Sent newsletter. Top={len(top)}, More={len(more)}")
    elif args.cmd == "preview":
        # Harvest, render, and write to files locally without sending email
        ensure_sources(); harvest()
        top, more = select_and_score()
        html, text = render_newsletter(top, more)
        out_dir = os.path.join(os.getcwd(), "newsletter_output")
        os.makedirs(out_dir, exist_ok=True)
        html_path = os.path.join(out_dir, "newsletter_preview.html")
        txt_path = os.path.join(out_dir, "newsletter_preview.txt")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Wrote preview files:\n- {html_path}\n- {txt_path}")
