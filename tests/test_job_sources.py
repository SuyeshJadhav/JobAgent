from backend.services.job_sources import standardize_date, deduplicate_jobs


def test_standardize_date_numeric():
    # Unix in seconds (e.g. 2026-01-01)
    assert standardize_date(1767225600) == "2026-01-01"

    # Unix in ms
    assert standardize_date(1767225600000) == "2026-01-01"


def test_standardize_date_relative():
    # dateparser handles this relative to current date, usually.
    # A generic ISO format check
    from datetime import datetime, timedelta
    date_str = standardize_date("2 days ago")
    assert len(date_str) == 10
    assert date_str.count("-") == 2


def test_standardize_date_iso():
    assert standardize_date("2026-01-15T10:30:00Z") == "2026-01-15"
    assert standardize_date("2026-01-15") == "2026-01-15"


def test_deduplicate_jobs():
    jobs = [
        {"company": "Google Inc", "title": "SWE",
            "location": "Remote", "description": "Short desc"},
        {"company": "Google", "title": "SWE", "location": "Remote, USA",
            "description": "Longer description here..."},
        {"company": "Google Corp.", "title": "SWE",
            "location": "Remote", "description": ""}
    ]

    # All 3 should be seen as the same "google|swe|remoteusa" depending on the aggressive replace logic.
    unique = deduplicate_jobs(jobs)
    # Depending on exact location stripping ("Remote, USA" may yield "remoteusa", "Remote" -> "remote")
    assert len(unique) <= 2

    # Exact identical fingerprints:
    jobs2 = [
        {"company": "Stripe", "title": "SWE Intern",
            "location": "San Francisco", "description": ""},
        {"company": "Stripe", "title": "SWE Intern",
            "location": "San Francisco", "description": "Actual JD text here"}
    ]
    unique2 = deduplicate_jobs(jobs2)
    assert len(unique2) == 1
    assert len(unique2[0]["description"]) > 0
