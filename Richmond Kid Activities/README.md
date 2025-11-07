# Richmond Kids — Weekly Family Activities

Lightweight pipeline to harvest family-friendly events around Richmond, VA; normalize and score them; and send a weekly email newsletter.

## Quickstart

1. python -m venv .venv && . .venv/Scripts/activate (Windows) or source .venv/bin/activate (macOS/Linux)
2. pip install -e .
3. Copy .env.example to .env and fill values (or export as env vars)
4. rk init
5. rk preview  # generates newsletter_output/newsletter_preview.html (no email)
6. rk weekly   # renders and sends via SMTP

`rk preview` writes HTML and plaintext files locally so you can review before emailing. `rk weekly` sends via SMTP. Edit `src/rk/sources.py` to add sources.

## Notes

- Uses SQLite for storage (path via `DB_PATH`). Ensure its parent folder exists; `rk init` will create it.
- Extractors: Schema.org (JSON-LD), RSS, ICS, and a generic HTML→LLM extractor using OpenAI Structured Outputs.
- GitHub Actions workflow included at `.github/workflows/weekly.yml` for Friday morning sends.
