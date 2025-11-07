from __future__ import annotations
import smtplib
from email.message import EmailMessage
from jinja2 import Environment, PackageLoader, select_autoescape
from .config import CFG


env = Environment(
    loader=PackageLoader("rk", "templates"),
    autoescape=select_autoescape()
)


def render_newsletter(top: list[dict], more: list[dict]) -> tuple[str, str]:
    tpl = env.get_template("newsletter.html.j2")
    html = tpl.render(top=top, more=more)
    text = "\n".join(
        ["Top Picks:"] + [f"- {e['title']} ({e['start_dt']}) @ {e.get('venue_name') or ''}" for e in top] +
        ["", "More:"] + [f"- {e['title']} ({e['start_dt']})" for e in more]
    )
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

