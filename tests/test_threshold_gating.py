from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.routers.sniper import AnswerRequest, get_sniper_answers
from backend.routers.tailor import (
    GenerateRequest,
    generate_cover_letter,
    generate_tailored_resume,
)


@patch("backend.routers.tailor.get_settings", return_value={"resume_match_threshold": 80})
@patch("backend.routers.tailor._resolve_job", return_value={"job_id": "job-1", "score": 70})
def test_generate_tailored_resume_rejects_below_threshold(_mock_resolve_job, _mock_settings):
    with pytest.raises(HTTPException) as exc_info:
        generate_tailored_resume(GenerateRequest(job_id="job-1"))

    assert exc_info.value.status_code == 400
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["score"] == 70
    assert exc_info.value.detail["threshold"] == 80
    assert exc_info.value.detail["tailoring_allowed"] is False


@patch("backend.routers.tailor.get_settings", return_value={"resume_match_threshold": 80})
@patch("backend.routers.tailor._resolve_job", return_value={"job_id": "job-2", "score": 40})
def test_generate_cover_letter_rejects_below_threshold(_mock_resolve_job, _mock_settings):
    with pytest.raises(HTTPException) as exc_info:
        generate_cover_letter(GenerateRequest(job_id="job-2"))

    assert exc_info.value.status_code == 400
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["score"] == 40
    assert exc_info.value.detail["threshold"] == 80
    assert exc_info.value.detail["tailoring_allowed"] is False


@patch("backend.routers.sniper.load_job_details", return_value={"description": "A" * 200})
@patch("backend.routers.sniper.get_settings", return_value={"resume_match_threshold": 80})
@patch("backend.routers.sniper.get_jobs", return_value=[{"job_id": "job-3", "score": 60}])
def test_sniper_answer_rejects_below_threshold_with_metadata(_mock_jobs, _mock_settings, _mock_details):
    payload = AnswerRequest(job_id="job-3", questions=["Why this role?"])

    with pytest.raises(HTTPException) as exc_info:
        get_sniper_answers(payload)

    assert exc_info.value.status_code == 400
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail["score"] == 60
    assert exc_info.value.detail["threshold"] == 80
    assert exc_info.value.detail["tailoring_allowed"] is False
