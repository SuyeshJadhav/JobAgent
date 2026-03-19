def resolve_score_threshold(settings: dict) -> int:
    """Resolve threshold on 0-100 scale with backward compatibility for 0-10 configs."""
    raw = settings.get("resume_match_threshold")
    if raw is None:
        system_cfg = settings.get("system", {}) if isinstance(
            settings.get("system", {}), dict) else {}
        raw = settings.get("score_threshold",
                           system_cfg.get("score_threshold", 80))

    try:
        val = int(raw)
    except (TypeError, ValueError):
        return 80

    if 0 <= val <= 10:
        return val * 10
    return max(0, min(100, val))


def normalize_score_to_percent(score: int | str | None) -> int:
    try:
        val = int(score)
    except (TypeError, ValueError):
        return 0

    if 0 <= val <= 10:
        return val * 10
    return max(0, min(100, val))


def threshold_rejection_detail(score: int, threshold: int, reason: str) -> dict:
    return {
        "reason": reason,
        "score": score,
        "threshold": threshold,
        "tailoring_allowed": False,
    }
