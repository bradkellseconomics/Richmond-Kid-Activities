from __future__ import annotations


def score_event(ev: dict, kids_ages=(5, 8)) -> float:
    score = 0.0
    # Age fit (soft)
    amin, amax = ev.get("age_min"), ev.get("age_max")
    if amin is None and amax is None:
        score += 5
    else:
        for k in kids_ages:
            if (amin is None or k >= amin) and (amax is None or k <= amax):
                score += 10
    # Cost bonus
    cm, cx = ev.get("cost_min"), ev.get("cost_max")
    if cm is None and cx is None:
        score += 5
    elif (cm or 0) == 0:
        score += 10
    # Category nudges
    cat = (ev.get("category") or "").lower()
    if any(x in cat for x in ["museum", "science", "library", "garden", "park"]):
        score += 5
    return score

