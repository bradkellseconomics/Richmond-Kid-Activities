from __future__ import annotations
import smtplib
from email.message import EmailMessage
from jinja2 import Environment, PackageLoader, select_autoescape
from dateutil import parser as dtp
from .config import CFG


env = Environment(
    loader=PackageLoader("rk", "templates"),
    autoescape=select_autoescape()
)


def _fmt_dt(s: str) -> str:
    try:
        dt = dtp.parse(s)
        # If exactly midnight, treat as unknown time to avoid fake 12:00 AM
        if dt.hour == 0 and dt.minute == 0:
            return dt.strftime("%a %b %d") + ", Time TBD"
        return dt.strftime("%a %b %d, %I:%M %p").lstrip("0").replace(" 0", " ")
    except Exception:
        return s


def _snippet(text: str, limit: int = 240) -> str:
    if not text:
        return ""
    t = " ".join(text.split())
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


env.filters["fmt_dt"] = _fmt_dt
env.filters["snippet"] = _snippet


def render_newsletter(sections: list[dict], week_range: str | None = None) -> tuple[str, str]:
    """`sections` is a list of {"label": str, "events": list[dict], "detailed": bool},
    e.g. from rk.pipeline.bucket_sections."""
    tpl = env.get_template("newsletter.html.j2")
    html = tpl.render(sections=sections, week_range=week_range)

    def _src(e):
        return f" via {e.get('source_name')}" if e.get('source_name') else ""

    lines = []
    for sec in sections:
        lines.append("")
        lines.append(f"{sec['label']}:")
        for e in sec["events"]:
            line = f"- {e['title']} ({e['start_dt']}) @ {e.get('venue_name') or ''}{_src(e)}"
            if e.get('occurrence_summary'):
                line += f"\n    {e['occurrence_summary']}"
            if sec.get("detailed") and e.get('_reason'):
                line += f"\n    Why: {e['_reason']}"
            lines.append(line)
    text = "\n".join(lines).strip()
    return html, text


def send_email(subject: str, html: str, text: str):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = CFG.from_email
    msg["To"] = ", ".join(CFG.to_emails)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(CFG.smtp_host, CFG.smtp_port) as s:
        s.starttls()
        s.login(CFG.smtp_user, CFG.smtp_pass)
        s.send_message(msg)
