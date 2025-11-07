from __future__ import annotations
import os
from dataclasses import dataclass
from dotenv import load_dotenv
 
# Load .env from project root if present
load_dotenv()


@dataclass(frozen=True)
class Config:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_pass: str = os.getenv("SMTP_PASS", "")
    from_email: str = os.getenv("FROM_EMAIL", "")
    to_emails: list[str] = tuple(e.strip() for e in os.getenv("TO_EMAILS","" ).split(",") if e.strip())
    db_path: str = os.getenv("DB_PATH", "./data/richmond.db")


CFG = Config()
