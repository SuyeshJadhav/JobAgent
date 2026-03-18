from backend.services.job_sources import (
    _is_us_or_remote,
    _title_matches_role,
    extract_company_from_url,
    normalize_job_types,
)


def test_normalize_job_types_splits_recognized_and_ignored():
    recognized, ignored = normalize_job_types(
        ["Internship", "newgrad", "software", "FULLTIME"])

    assert recognized == ["internship", "newgrad", "fulltime"]
    assert ignored == ["software"]


def test_is_us_or_remote_accepts_expected_markers():
    assert _is_us_or_remote("Remote - United States") is True
    assert _is_us_or_remote("Austin, USA") is True
    assert _is_us_or_remote("Berlin, Germany") is False


def test_title_matches_role_is_case_insensitive():
    assert _title_matches_role(
        "Software Engineer Internship", "software engineer") is True
    assert _title_matches_role("Data Analyst", "software engineer") is False


def test_extract_company_from_lever_url():
    company = extract_company_from_url("https://jobs.lever.co/notion/abcd1234")
    assert company == "Notion"


def test_extract_company_from_greenhouse_url():
    company = extract_company_from_url(
        "https://boards.greenhouse.io/stripe/jobs/123456")
    assert company == "Stripe"
