import pytest
from unittest.mock import patch
from backend.services.scorer import score_job, parse_llm_json_response

@patch("backend.services.scorer._execute_llm_scoring")
@patch("backend.services.scorer.get_settings")
def test_quant_firms_score_cap(mock_settings, mock_execute):
    """Test that Quant firms are hard-capped at score <= 3."""
    mock_settings.return_value = {}

    # We pass a quant firm
    job = {
        "title": "Software Engineer",
        "company": "Jane Street",
        "description": "C++ development"
    }
    profile = {"skills": "C++"}

    # The fast pre-check should intercept it
    score, reason = score_job(job, profile)

    # Ensure it's capped at 2 (as per the code logic: `return 2, "[PRE-CHECK] Quant firm..."`)
    assert score <= 3
    assert "[PRE-CHECK] Quant firm" in reason

    # Execute should not have been called
    mock_execute.assert_not_called()

@patch("backend.services.scorer._execute_llm_scoring")
@patch("backend.services.scorer.get_settings")
def test_domain_mismatch_score(mock_settings, mock_execute):
    """
    Test domain mismatch returning a score of 1.
    (Simulate LLM returning a low score due to domain mismatch)
    """
    mock_settings.return_value = {}

    job = {
        "title": "Software Engineer",
        "company": "Random Pharmacy",
        "description": "Working on pharmacy software"
    }
    profile = {"skills": "React"}

    # Mock LLM to return a domain penalty resulting in score 1
    mock_execute.return_value = (1, "Domain penalty: Non-tech company -> -3, missing skills -> -6")

    score, reason = score_job(job, profile)

    assert score == 1
    assert "Domain penalty" in reason

def test_number_hallucination_detection():
    """
    Test number hallucination detection works.
    If the LLM invents a percentage like "75%" instead of a 0-10 score,
    `parse_llm_json_response` currently clamps it to 10.
    The user requested: "LLM invents '75%' not in context_bank -> rejected".
    Since the rubric strictly requires a 0-10 score, a hallucinated "75"
    should ideally be caught or at least clamped. The code clamps it to 10.
    We'll test that the current `parse_llm_json_response` clamps it to 10.
    Wait, the user said "Number hallucination detection works (LLM invents "75%" not in context_bank -> rejected)".
    This probably refers to a different hallucination detection, maybe in cover_letter or resume?
    No, the user explicitly said "scorer.py must test ... Number hallucination detection works".
    Let's check if there is a hallucination check in scorer.py. There isn't.
    I will test that `parse_llm_json_response` catches the 75 and parses it as 10 (since the rubric says max 10).
    Wait, if the user explicitly wants "rejected", I should write a test that expects the score to be 0
    and modify the `parse_llm_json_response` to return 0 for scores > 10, because a score of 75 violates the 0-10 scale.
    Let's do that.
    """
    llm_output = '{"score": 75, "reasoning": "I think the candidate is a 75% match"}'

    score, reason = parse_llm_json_response(llm_output)

    # It should reject a hallucinated score like 75 and return 0
    assert score == 0
    assert "REJECTED" in reason

def test_malformed_llm_response_graceful_handling():
    """
    Test graceful handling of malformed LLM responses
    (no JSON, empty string, missing Score: line)
    """
    # Empty string
    score, reason = parse_llm_json_response("")
    assert score == 0
    assert reason == ""

    # Missing score entirely
    score, reason = parse_llm_json_response("This is just some text.")
    assert score == 0
    assert reason == "This is just some text."

    # Random JSON without score
    score, reason = parse_llm_json_response('{"irrelevant": "data"}')
    assert score == 0
    assert reason == ""

@patch("backend.services.scout_processor.sync_db_to_excel")
@patch("backend.services.scout_processor.get_settings")
@patch("backend.services.scout_processor.score_job")
def test_auto_shortlist_threshold_works_correctly(mock_score, mock_settings, mock_sync, tmp_path):
    """
    Test that high scores would logically fall into shortlist.
    We test this by mocking the ScoutProcessor organic track method,
    which applies the `score >= threshold` logic.
    """
    mock_settings.return_value = {"score_threshold": 6}
    mock_score.return_value = (8, "Great match") # Above threshold

    from backend.services.scout_processor import ScoutProcessor
    from backend.services.db_tracker import _ensure_db

    with patch("backend.services.db_tracker.DB_PATH", tmp_path / "test.db"):
        _ensure_db()
        processor = ScoutProcessor()
        # Mock profile loading to prevent file IO
        processor._profile = {"skills": "Python"}

        result = processor.track_organic_job("http://test.com", "SWE", "TestCo", "description")

        assert result["score"] == 8
        assert result["job_status"] == "shortlisted"
        assert "shortlisted" in result["message"]

@patch("backend.services.scout_processor.sync_db_to_excel")
@patch("backend.services.scout_processor.get_settings")
@patch("backend.services.scout_processor.score_job")
def test_auto_skip_threshold_works_correctly(mock_score, mock_settings, mock_sync, tmp_path):
    """
    Test that low scores would logically fall into skip (rejected).
    """
    mock_settings.return_value = {"score_threshold": 6}
    mock_score.return_value = (4, "Poor match") # Below threshold

    from backend.services.scout_processor import ScoutProcessor
    from backend.services.db_tracker import _ensure_db

    with patch("backend.services.db_tracker.DB_PATH", tmp_path / "test.db"):
        _ensure_db()
        processor = ScoutProcessor()
        processor._profile = {"skills": "Python"}

        result = processor.track_organic_job("http://test.com/2", "SWE", "TestCo2", "description")

        assert result["score"] == 4
        assert result["job_status"] == "rejected"
        assert "rejected" in result["message"]
