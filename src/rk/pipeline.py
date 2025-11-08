from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import engine, SessionLocal, Base
from .models import Source, Event
from .extractors.schema_org import SchemaOrgExtractor
from .extractors.rss_reader import RSSExtractor
from .extractors.ics_reader import ICSExtractor
from .extractors.html_llm import HTMLLLMExtractor
from .extractors.macaroni_kid import MacaroniKidExtractor
from .scoring import score_event
from rapidfuzz import fuzz
from urllib.parse import urlparse
from dateutil import parser as dtp
from dateutil import tz as dttz
from .config import CFG


EXTRACTORS = {
    "schema_org": SchemaOrgExtractor(),
    "rss": RSSExtractor(),
    "ics": ICSExtractor(),
    "html": HTMLLLMExtractor(),
    "macaronikid": MacaroniKidExtractor(),
}

LOCAL_TZ = dttz.gettz("America/New_York")


def init_db():
    # Ensure the parent directory for SQLite exists
    db_dir = os.path.dirname(CFG.db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    Base.metadata.create_all(engine)


def upsert_events(session, source: Source, events: list[dict]) -> int:
    added = 0
    now = datetime.now(timezone.utc)
    for d in events:
        ev = Event(**d, source_id=source.id, first_seen=now, last_seen=now, status="active")
        try:
            session.add(ev)
            session.commit()
            added += 1
        except IntegrityError:
            session.rollback()
    return added


def harvest():
    init_db()
    with SessionLocal() as s:
        sources = list(s.scalars(select(Source).where(Source.active == 1)))
        total = 0
        for src in sources:
            ex = EXTRACTORS.get(src.kind)
            if not ex:
                continue
            # For HTML sources, try schema.org first as a structured fallback
            schema_norm = []
            if src.kind == "html":
                try:
                    so_raw = EXTRACTORS["schema_org"].discover(src.url)
                    schema_norm = EXTRACTORS["schema_org"].normalize(so_raw)
                    if schema_norm:
                        added = upsert_events(s, src, [n.data for n in schema_norm])
                        print(f"[INFO] {src.name} | kind=schema_org(fallback) | discovered={len(so_raw)} normalized={len(schema_norm)} added={added}")
                        total += added
                        # Continue to next source if schema.org yielded events
                        continue
                except Exception as e:
                    print(f"[WARN] schema_org fallback failed for {src.url}: {e}")

            try:
                raw = ex.discover(src.url)
            except Exception as e:
                print(f"[WARN] discover failed for {src.url}: {e}")
                raw = []
            try:
                norm_objs = ex.normalize(raw)
            except Exception as e:
                print(f"[WARN] normalize failed for {src.url}: {e}")
                norm_objs = []
            norm = [n.data for n in norm_objs]
            added = upsert_events(s, src, norm)
            print(f"[INFO] {src.name} | kind={src.kind} | discovered={len(raw)} normalized={len(norm)} added={added}")
            total += added
        return total


def window_next_week(start_day="sat"):
    # Saturday through Friday window in America/New_York
    now_local = datetime.now(LOCAL_TZ)
    offset = (5 - now_local.weekday()) % 7 if start_day == "sat" else 0
    start = (now_local + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return start, end


def _to_local_aware(dt_in):
    """
    Accepts str or datetime. Returns tz-aware datetime in America/New_York.
    If input is date-only (no time), default to 09:00 local.
    """
    if dt_in is None:
        return None
    date_only = False
    if isinstance(dt_in, str):
        s = dt_in.strip()
        # Heuristic for date-only strings (no time components)
        date_only = (":" not in s and "T" not in s and not any(x in s.lower() for x in ["am", "pm"]))
        try:
            d = dtp.parse(s)
        except Exception:
            return None
    else:
        d = dt_in
    if d.tzinfo is None:
        if date_only:
            d = d.replace(hour=9, minute=0, second=0, microsecond=0)
        d = d.replace(tzinfo=LOCAL_TZ)
    else:
        d = d.astimezone(LOCAL_TZ)
    return d


def select_and_score():
    start, end = window_next_week("sat")
    with SessionLocal() as s:
        evs = list(s.scalars(select(Event)))
        # Map source_id -> source name for display
        src_map = {src.id: src.name for src in s.scalars(select(Source))}
        picked = []
        for e in evs:
            st = _to_local_aware(e.start_dt)
            if not st:
                continue
            if not (start <= st <= end):
                continue
            d = {c.name: getattr(e, c.name) for c in Event.__table__.columns}
            d["_score"] = score_event(d)
            d["source_name"] = src_map.get(e.source_id, "")
            picked.append(d)
        picked.sort(key=lambda x: x["_score"], reverse=True)

        def _norm_title(t: str) -> str:
            return " ".join((t or "").lower().split())

        def _domain(u: str | None) -> str:
            try:
                return urlparse(u or "").netloc
            except Exception:
                return ""

        def _is_dupe(a: dict, b: dict) -> bool:
            sa = _to_local_aware(a.get("start_dt")); sb = _to_local_aware(b.get("start_dt"))
            if not sa or not sb:
                return False
            # Within 3 hours on same day
            if sa.date() != sb.date():
                return False
            if abs((sa - sb).total_seconds()) > 3 * 3600:
                return False
            # Title similarity high
            if fuzz.ratio(_norm_title(a.get("title","")), _norm_title(b.get("title",""))) < 90:
                return False
            # If venues present for both, require reasonably close
            va, vb = (a.get("venue_name") or ""), (b.get("venue_name") or "")
            if va and vb and fuzz.ratio(va.lower(), vb.lower()) < 85:
                return False
            # If registration URLs present, prefer same domain or ignore
            da, db = _domain(a.get("registration_url")), _domain(b.get("registration_url"))
            if da and db and da != db:
                # Different domains might still be same event; don't block, just allow
                pass
            return True

        def _dedupe(sorted_events: list[dict]) -> list[dict]:
            unique: list[dict] = []
            for ev in sorted_events:
                if not any(_is_dupe(ev, u) for u in unique):
                    unique.append(ev)
            return unique

        deduped = _dedupe(picked)

        def _norm_title(t: str) -> str:
            return " ".join((t or "").lower().split())

        def _group(sorted_events: list[dict]) -> list[dict]:
            groups: dict[tuple, list[dict]] = {}
            for ev in sorted_events:
                key = (
                    _norm_title(ev.get("title", "")),
                    (ev.get("venue_name") or "").strip().lower(),
                    urlparse(ev.get("registration_url") or "").netloc,
                )
                groups.setdefault(key, []).append(ev)

            out: list[dict] = []
            for key, items in groups.items():
                items.sort(key=lambda x: x.get("_score", 0), reverse=True)
                base = dict(items[0])
                # Collect occurrences (unique, sorted)
                times = []
                seen = set()
                for it in items:
                    iso = it.get("start_dt")
                    if not iso or iso in seen:
                        continue
                    seen.add(iso)
                    try:
                        dt = dtp.parse(iso)
                        times.append(dt)
                    except Exception:
                        continue
                times.sort()
                base["occurrences"] = [t.isoformat() for t in times]
                # Build a compact summary for multiple occurrences
                if len(times) > 1:
                    first = times[0]
                    same_day = all(t.date() == first.date() for t in times)
                    if same_day:
                        # Additional times on same day
                        more_times = [t.strftime("%I:%M %p").lstrip("0").replace(" 0", " ") for t in times[1:]]
                        if more_times:
                            base["occurrence_summary"] = "Additional times: " + ", ".join(more_times)
                    else:
                        start = times[0]
                        end = times[-1]
                        base["occurrence_summary"] = f"Runs: {start.strftime('%b %d')}–{end.strftime('%b %d')} ({len(times)} times)"
                out.append(base)
            # Preserve original ranking: sort groups by top item's score
            out.sort(key=lambda x: x.get("_score", 0), reverse=True)
            return out

        grouped = _group(deduped)
        return grouped[:12], grouped[12:40]


def select_grouped_all():
    start, end = window_next_week("sat")
    with SessionLocal() as s:
        evs = list(s.scalars(select(Event)))
        src_map = {src.id: src.name for src in s.scalars(select(Source))}
        picked = []
        for e in evs:
            st = _to_local_aware(e.start_dt)
            if not st:
                continue
            if not (start <= st <= end):
                continue
            d = {c.name: getattr(e, c.name) for c in Event.__table__.columns}
            d["_score"] = score_event(d)
            d["source_name"] = src_map.get(e.source_id, "")
            picked.append(d)
        picked.sort(key=lambda x: x["_score"], reverse=True)

        def _norm_title(t: str) -> str:
            return " ".join((t or "").lower().split())

        def _domain(u: str | None) -> str:
            try:
                return urlparse(u or "").netloc
            except Exception:
                return ""

        def _is_dupe(a: dict, b: dict) -> bool:
            sa = _to_local_aware(a.get("start_dt")); sb = _to_local_aware(b.get("start_dt"))
            if not sa or not sb:
                return False
            if sa.date() != sb.date():
                return False
            if abs((sa - sb).total_seconds()) > 3 * 3600:
                return False
            if fuzz.ratio(_norm_title(a.get("title","")), _norm_title(b.get("title",""))) < 90:
                return False
            va, vb = (a.get("venue_name") or ""), (b.get("venue_name") or "")
            if va and vb and fuzz.ratio(va.lower(), vb.lower()) < 85:
                return False
            return True

        def _dedupe(sorted_events: list[dict]) -> list[dict]:
            unique: list[dict] = []
            for ev in sorted_events:
                if not any(_is_dupe(ev, u) for u in unique):
                    unique.append(ev)
            return unique

        def _group(sorted_events: list[dict]) -> list[dict]:
            groups: dict[tuple, list[dict]] = {}
            for ev in sorted_events:
                key = (
                    _norm_title(ev.get("title", "")),
                    (ev.get("venue_name") or "").strip().lower(),
                    urlparse(ev.get("registration_url") or "").netloc,
                )
                groups.setdefault(key, []).append(ev)

            out: list[dict] = []
            for key, items in groups.items():
                items.sort(key=lambda x: x.get("_score", 0), reverse=True)
                base = dict(items[0])
                times = []
                seen = set()
                for it in items:
                    iso = it.get("start_dt")
                    if not iso or iso in seen:
                        continue
                    seen.add(iso)
                    try:
                        dt = dtp.parse(iso)
                        times.append(dt)
                    except Exception:
                        continue
                times.sort()
                base["occurrences"] = [t.isoformat() for t in times]
                if len(times) > 1:
                    first = times[0]
                    same_day = all(t.date() == first.date() for t in times)
                    if same_day:
                        more_times = [t.strftime("%I:%M %p").lstrip("0").replace(" 0", " ") for t in times[1:]]
                        if more_times:
                            base["occurrence_summary"] = "Additional times: " + ", ".join(more_times)
                    else:
                        start_d = times[0]
                        end_d = times[-1]
                        base["occurrence_summary"] = f"Runs: {start_d.strftime('%b %d')}–{end_d.strftime('%b %d')} ({len(times)} times)"
                out.append(base)
            out.sort(key=lambda x: x.get("_score", 0), reverse=True)
            return out

        deduped = _dedupe(picked)
        grouped = _group(deduped)
        return grouped
