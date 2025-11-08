from __future__ import annotations
import requests, hashlib
from ics import Calendar
from dateutil import tz
from .base import Extractor, RawItem, NormalizedEvent


class ICSExtractor(Extractor):
    kind = "ics"

    def discover(self, source_url: str) -> list[RawItem]:
        from urllib.parse import urlparse, urlunparse

        # Normalize webcal:// to https:// (many calendar links use the webcal scheme)
        try:
            u0 = urlparse(source_url)
            if u0.scheme.lower().startswith("webcal"):
                # Prefer https when switching from webcal
                source_url = urlunparse(("https", u0.netloc, u0.path, u0.params, u0.query, u0.fragment))
        except Exception:
            pass

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 rk-bot/1.0"
            ),
            "Accept": "text/calendar, text/plain;q=0.9, */*;q=0.8",
        }

        def _fetch(url: str):
            return requests.get(url, timeout=25, headers=headers)

        try:
            r = _fetch(source_url)
            r.raise_for_status()
        except requests.exceptions.SSLError:
            # Retry without 'www.' if present
            try:
                u = urlparse(source_url)
                host = u.netloc.replace("www.", "")
                fallback = urlunparse((u.scheme, host, u.path, u.params, u.query, u.fragment))
                r = _fetch(fallback)
                r.raise_for_status()
            except Exception as e2:
                print(f"[WARN] SSL/host fallback failed for {source_url}: {e2}")
                return []
        except requests.exceptions.HTTPError as e:
            # Some servers vary by UA; try host fallback before giving up
            try:
                u = urlparse(source_url)
                host = u.netloc.replace("www.", "")
                fallback = urlunparse((u.scheme, host, u.path, u.params, u.query, u.fragment))
                if fallback != source_url:
                    r = _fetch(fallback)
                    r.raise_for_status()
                else:
                    raise e
            except Exception as e2:
                print(f"[WARN] ICS discover failed for {source_url}: {e} / fallback: {e2}")
                return []
        except Exception as e:
            print(f"[WARN] ICS discover failed for {source_url}: {e}")
            return []

        return [RawItem(source_url=source_url, payload={"ics": r.text})]

    def normalize(self, items: list[RawItem]) -> list[NormalizedEvent]:
        out = []
        for it in items:
            cal = Calendar(it.payload["ics"])
            for e in cal.events:
                title = (e.name or "").strip()
                start_iso = e.begin.astimezone(tz.gettz("America/New_York")).isoformat() if e.begin else None
                end_iso = e.end.astimezone(tz.gettz("America/New_York")).isoformat() if e.end else None
                uid = hashlib.sha1(f"{it.source_url}|{title}|{start_iso}".encode()).hexdigest()[:20]
                cats = None
                try:
                    cats_val = getattr(e, 'categories', None)
                    if cats_val:
                        # 'categories' may be set or list-like
                        cats = ",".join(sorted(list(cats_val))) if not isinstance(cats_val, str) else cats_val
                except Exception:
                    cats = None

                data = {
                    "uid": uid, "source_url": it.source_url, "title": title,
                    "description": (e.description or "").strip(),
                    "category": cats or "general", "age_min": None, "age_max": None,
                    "start_dt": start_iso, "end_dt": end_iso, "tz": "America/New_York",
                    "venue_name": (e.location or None), "address": None, "lat": None, "lng": None,
                    "cost_min": None, "cost_max": None, "registration_url": getattr(e, 'url', None), "tags": {}
                }
                out.append(NormalizedEvent(uid=uid, data=data))
        return out
