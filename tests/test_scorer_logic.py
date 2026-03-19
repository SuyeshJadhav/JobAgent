from unittest.mock import patch

from backend.services.scorer import parse_llm_json_response, score_job


def test_parse_llm_json_response_handles_markdown_wrapped_json():
    content = """```json
    {"score": 8, "reasoning": "Strong fit", "company": "Acme", "title": "SWE Intern", "strategy": "skills_only"}
    ```"""

    result = parse_llm_json_response(content)

    assert result["score"] == 8
    assert result["reasoning"] == "Strong fit"
    assert result["company"] == "Acme"
    assert result["title"] == "SWE Intern"
    assert result["strategy"] == "skills_only"


def test_parse_llm_json_response_falls_back_to_regex_when_invalid_json():
    content = 'score: broken {"score": 11, "reasoning": "Too high", "company": "Acme", "title": "Role"}'

    result = parse_llm_json_response(content)

    # Score is clamped to 0-100 in parser
    assert result["score"] == 11
    assert result["company"] == "Acme"
    assert result["title"] == "Role"


def test_score_job_quant_company_is_capped_without_llm():
    job = {
        "title": "Software Engineer Intern",
        "company": "Jane Street",
        "description": "Internship role",
    }
    profile = {"target_roles": "SWE Intern"}

    result = score_job(job, profile)

    assert result["score"] == 20
    assert "Quant firm" in result["reasoning"]


def test_score_job_senior_title_is_auto_rejected_without_llm():
    job = {
        "title": "Senior Software Engineer",
        "company": "Acme",
        "description": "Requires 5+ years",
    }
    profile = {"target_roles": "SWE Intern"}

    result = score_job(job, profile)

    assert result["score"] == 0
    assert "Senior/Staff/Lead role" in result["reasoning"]


@patch("backend.services.scorer.get_settings")
@patch("backend.services.scorer._llm_score")
def test_score_job_adds_sponsorship_bonus(mock_llm_score, mock_get_settings):
    mock_llm_score.return_value = {
        "score": 70,
        "reasoning": "Base score",
        "company": "Acme",
        "title": "SWE Intern",
        "strategy": "skills_only",
    }
    mock_get_settings.return_value = {"visa_status": "prefer_sponsorship"}

    job = {
        "title": "Software Engineer Intern",
        "company": "Acme",
        "description": "Intern role",
        "is_sponsored": True,
    }
    profile = {"target_roles": "SWE Intern"}

    result = score_job(job, profile)

    assert result["score"] == 80
    assert result["reasoning"].startswith("[SPONSORED]")
