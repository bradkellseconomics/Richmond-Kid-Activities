from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load .env from project root if present
load_dotenv()

# One entry per kid, birthdate-based so age is always current instead of a
# snapshot that goes stale. Override entirely via KIDS_JSON in .env, e.g.:
# KIDS_JSON=[{"name":"F","birthdate":"2025-04-02","interests":[]},{"name":"L","birthdate":"2023-07-02","interests":["dinosaurs"]}]
_DEFAULT_KIDS = [
    {"name": "F", "birthdate": "2025-04-02", "interests": []},
    {"name": "L", "birthdate": "2023-07-02", "interests": ["dinosaurs", "animals", "construction/trucks", "books"]},
]

# Where the family lives, in plain language — used by the ranker to weigh
# venue convenience (a nearby branch beats a 20-minute drive to Glen Allen
# even for an otherwise well-matched event). Override via HOME_LOCATION.
_DEFAULT_HOME_LOCATION = (
    "Richmond, VA, near the Belmont library branch. Strongly prefer Belmont, "
    "Main (downtown), Libbie Mill, and Westover Hills libraries, plus other "
    "venues within Richmond city or close-in Henrico/Chesterfield. Avoid "
    "favoring venues that are a real drive away (e.g. Glen Allen or other "
    "far Henrico/Chesterfield suburbs) unless the event is an exceptional, "
    "can't-miss match — cap those at \"good\" rather than \"top\" so they "
    "land in More Options instead of a top-pick section."
)


def _load_kids() -> tuple[dict, ...]:
    raw = os.getenv("KIDS_JSON", "").strip()
    if raw:
        return tuple(json.loads(raw))
    return tuple(_DEFAULT_KIDS)


@dataclass(frozen=True)
class Config:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_pass: str = os.getenv("SMTP_PASS", "")
    from_email: str = os.getenv("FROM_EMAIL", "")
    to_emails: list[str] = tuple(e.strip() for e in os.getenv("TO_EMAILS","" ).split(",") if e.strip())
    db_path: str = os.getenv("DB_PATH", "./data/richmond.db")
    kids: tuple[dict, ...] = field(default_factory=_load_kids)
    home_location: str = os.getenv("HOME_LOCATION", _DEFAULT_HOME_LOCATION)


CFG = Config()
