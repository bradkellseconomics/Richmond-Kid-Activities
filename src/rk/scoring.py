from __future__ import annotations
import re
from dateutil import parser as dtp
from .config import CFG

# --- Lexical features (robust, not brittle) -----------------

ADULT_TERMS = [
    r"\b21\s*\+\b", r"\b21\s*(?:and\s*(?:over|older))\b", r"\badults?\s*only\b",
    r"\bflight(s)?\b", r"\bwine\b", r"\bbeer\b", r"\bbrew(ery|pub)\b", r"\bcocktail(s)?\b",
    r"\btaproom\b", r"\bdistiller(y|ies)\b", r"\bwinery\b", r"\bcider(y)?\b", r"\bhappy\s*hour\b",
]

OLDER_FORMATS = [
    r"\b(comedy|improv|stand-?up)\b", r"\bconcert\b", r"\borchestra\b", r"\brecital\b",
    r"\btheatre|theater|play\b", r"\bbook\s*sign(ing|s)?\b", r"\bauthor\s*talk\b", r"\blecture\b", r"\bseminar\b",
    r"\btrivia\b", r"\bnetwork(ing)?\b", r"\bbar\b", r"\bpub\b",
    r"\bteen(s|ager|agers)?\b", r"\byouth(?:\s+group)?\b", r"\bhigh\s*school\b", r"\bgrades?\s*(6|7|8|9|10|11|12)\b",
]

TODDLER_PROGRAMS = [
    r"\btoddler(s)?\b", r"\btots?\b", r"\bpreschool(ers)?\b", r"\bbab(y|ies)\b", r"\binfant(s)?\b",
    r"\bstory\s*time\b", r"\brhyme\s*time\b", r"\blapsit\b", r"\bparent\s*&?\s*me\b",
    r"\bsensory\s*(play|time)\b", r"\bopen\s*play\b", r"\bplay\s*group\b", r"\bmusic\s*(class|time)\b",
    r"\bmother\s*goose\b", r"\bstroller\b",
]

AGE_PHRASES = [
    r"\b(for|best\s*for|recommended\s*for)\s*ages?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\b",
    r"\bages?\s*(\d{1,2})\s*(?:to|–|-)\s*(\d{1,2})\b",
    r"\bages?\s*(\d{1,2})\s*\+\b",
    r"\b(?:18|24|36)\s*months\b",
]

# Weak, generic “family” verbiage = tiny nudge only
WEAK_FAMILY = [r"\bfamily[-\s]*friendly\b", r"\bfun for all ages\b", r"\bbring your (kids|children)\b", r"\bfamily (fun|event)\b"]

SAFE_VENUE_CATS = ["museum", "library", "science", "garden", "park", "nature", "botanical"]


def _has(pats, text: str) -> bool:
    return any(re.search(p, text, flags=re.I) for p in pats)

def _near(text: str, p_left: str, p_right: str, window_chars: int = 80) -> bool:
    """True if p_left and p_right appear within ~window characters."""
    t = text.lower()
    for m in re.finditer(p_left, t, flags=re.I):
        start = max(0, m.start() - window_chars); end = min(len(t), m.end() + window_chars)
        if re.search(p_right, t[start:end], flags=re.I):
            return True
    return False

def _time_score(ev):
    try:
        st = dtp.parse(ev.get("start_dt"))
    except Exception:
        return 0.0, None
    score = 0.0
    if st.weekday() in (5, 6):  # weekend
        score += 4
    if CFG.earliest_hour_ok <= st.hour <= CFG.latest_hour_ok:  # daytime
        score += 4
    if CFG.toddler_mode and st.hour >= CFG.latest_hour_ok + 1:  # late
        score -= 25
    return score, st

def _age_score(ev, kids_ages):
    amin, amax = ev.get("age_min"), ev.get("age_max")
    text = ((ev.get("title") or "") + " " + (ev.get("description") or "")).lower()

    # Explicit teen/adult language → heavy downweight in toddler mode
    if CFG.toddler_mode and re.search(r"\bteen(s|ager|agers)?\b|\badult(s)?\b", text):
        return -40

    if amin is None and amax is None:
        # Unknown age: reward only if there is toddler program wording OR a safe venue/category
        cat = (ev.get("category") or "").lower()
        if _has(TODDLER_PROGRAMS, text) or any(c in cat for c in SAFE_VENUE_CATS) or _has(AGE_PHRASES, text):
            return 6
        return (-8 if CFG.strict_age_required else 0)

    if CFG.toddler_mode and amin is not None and amin >= 4:
        return -30

    score = 0.0
    for k in kids_ages:
        if (amin is None or k >= amin) and (amax is None or k <= amax):
            score += 10.0
    return min(score, 30.0)

def _intent_score(text: str, cat_l: str) -> int:
    """Evidence > vibes: strong for toddler programs/age phrases; weak for generic 'family'."""
    s = 0
    if _has(TODDLER_PROGRAMS, text): s += 18
    if _has(AGE_PHRASES, text):      s += 10
    if _has(WEAK_FAMILY, text):      s += 2  # tiny nudge
    if any(c in cat_l for c in SAFE_VENUE_CATS): s += 6
    return s

def _format_penalty(text: str) -> int:
    """Penalize older-skew formats unless they carry nearby kid evidence."""
    # Base penalty
    pen = -18 if _has(OLDER_FORMATS, text) else 0
    if pen == 0:
        return 0
    # Soften/clear penalty if there is toddler evidence near the format mention
    kid_near = (
        _near(text, r"(book\s*sign(ing|s)?|author\s*talk)", r"(children|kids|picture\s*book|read-?aloud|story\s*time)")
        or _near(text, r"(comedy|improv)", r"(children|kids|family|matinee)")
        or _has(TODDLER_PROGRAMS, text)
        or _has(AGE_PHRASES, text)
    )
    if kid_near:
        return 0  # don’t punish a children’s author read-aloud
    return pen

def looks_toddler_friendly(ev: dict) -> bool:
    """Deterministic gate for Top Picks; keeps it broad but safe."""
    text = ((ev.get("title") or "") + " " + (ev.get("description") or "")).lower()
    if _has(ADULT_TERMS, text):
        return False
    try:
        st = dtp.parse(ev.get("start_dt"))
        if st.hour >= max(19, getattr(CFG, "latest_hour_ok", 19)) + 1:
            return False
    except Exception:
        pass
    amin = ev.get("age_min")
    if CFG.toddler_mode and amin is not None and amin >= 4:
        return False
    # unknown ages must show toddler intent or safe venue
    if amin is None and ev.get("age_max") is None:
        cat = (ev.get("category") or "").lower()
        if not (_has(TODDLER_PROGRAMS, text) or _has(AGE_PHRASES, text) or any(c in cat for c in SAFE_VENUE_CATS)):
            return False
    return True

def is_ambiguous(ev: dict) -> bool:
    """Use to keep ambiguous items out of Top Picks unless score is high."""
    text = ((ev.get("title") or "") + " " + (ev.get("description") or "")).lower()
    if _has(TODDLER_PROGRAMS, text) or _has(AGE_PHRASES, text):
        return False
    cat = (ev.get("category") or "").lower()
    if any(c in cat for c in SAFE_VENUE_CATS):
        return False
    return True

def score_event(ev: dict, kids_ages: tuple[int, ...] | None = None) -> float:
    if kids_ages is None:
        kids_ages = CFG.kids_ages

    title = (ev.get("title") or "")
    desc  = (ev.get("description") or "")
    cat   = (ev.get("category") or "")
    text  = f"{title}\n{desc}".lower()
    cat_l = cat.lower()

    score = 0.0

    # Hard negatives: explicit adult content/venues
    if _has(ADULT_TERMS, text):
        score -= 60
    # Bars disguised as “family day”
    if re.search(r"\bbrew|taproom|winery|cidery|distillery\b", text, re.I):
        score -= 30

    # Intent signals (evidence > vibes)
    score += _intent_score(text, cat_l)

    # Older-skew formats get a soft penalty unless toddler evidence is nearby
    score += _format_penalty(text)

    # Age fit
    score += _age_score(ev, kids_ages)

    # Cost
    cm, cx = ev.get("cost_min"), ev.get("cost_max")
    if cm == 0 or (cm is None and cx == 0):
        score += 10
    elif cm is None and cx is None:
        score += 1

    # Time
    ts, _ = _time_score(ev)
    score += ts

    # Tiny nudge for explicit family/kids words (kept weak)
    if re.search(r"\bfamil(y|ies)\b|\bkids?\b|\bchildren\b", text):
        score += 2

    # Ambiguity penalty (small): prefer clear toddler intent in Top Picks later
    if is_ambiguous(ev):
        score -= 4

    return round(score, 2)
