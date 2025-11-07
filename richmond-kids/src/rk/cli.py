from __future__ import annotations
import argparse
from .pipeline import harvest, select_and_score, init_db
from .sources import ensure_sources
from .emailer import render_newsletter, send_email


def main():
    ap = argparse.ArgumentParser("rk")
    ap.add_argument("cmd", choices=["init", "harvest", "weekly"])
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

