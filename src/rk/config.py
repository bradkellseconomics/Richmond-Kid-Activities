from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load .env from project root if present
load_dotenv()

# One entry per kid, birthdate-based so age is always current instead of a
# snapshot that goes stale. Override entirely via KIDS_JSON in .env, e.g.:
# KIDS_JSON=[{"name":"Kid 1","birthdate":"2025-04-02","interests":[]},{"name":"Kid 2","birthdate":"2023-07-02","interests":["dinosaurs"]}]
_DEFAULT_KIDS = [
    {"name": "Kid 1", "birthdate": "2025-04-02", "interests": []},
    {"name": "Kid 2", "birthdate": "2023-07-02", "interests": ["dinosaurs", "animals", "construction/trucks", "books"]},
]


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


CFG = Config()
