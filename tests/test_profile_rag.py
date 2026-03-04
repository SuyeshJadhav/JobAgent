import pytest
from unittest.mock import patch, MagicMock

from backend.services.profile_rag import (
    _handle_standard_fields,
    _generate_llm_answers,
    batch_fill_fields
)

# Task 2 — Test the Fast Path
@patch("backend.services.profile_rag._build_fast_path_map")
@patch("backend.services.profile_rag.cache_collection", MagicMock())
def test_handle_standard_fields_success(mock_fast_path):
    mock_fast_path.return_value = {
        "first name": "TestFirst",
        "email": "test@example.com"
    }
    
    # Mocking cache to return no match (distance > 0.4)
    from backend.services.profile_rag import cache_collection
    cache_collection.query.return_value = {
        "distances": [[1.0]],
        "metadatas": [[{"answer": "foo"}]],
        "documents": [["bar"]]
    }
    
    fields = ["First Name", "Email", "Why this company?"]
    results, llm_fields = _handle_standard_fields(fields)
    
    # Assert fast path caught the first two, left the last for LLM
    assert results == {"First Name": "TestFirst", "Email": "test@example.com"}
    assert llm_fields == ["Why this company?"]

# Task 3 — Test the LLM Generator (Mocked)
@patch("backend.services.profile_rag.get_llm_client")
@patch("backend.services.profile_rag.get_model_name", return_value="test-model")
@patch("backend.services.profile_rag.load_profile_file", return_value="fake profile data")
@patch("backend.services.profile_rag.cache_collection", MagicMock())
def test_generate_llm_answers_success(mock_load, mock_model, mock_getClient):
    mock_client = MagicMock()
    mock_getClient.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"Why this company?": "Because I love automation."}'
    mock_client.chat.completions.create.return_value = mock_response

    fields = ["Why this company?"]
    result = _generate_llm_answers(fields, "example.com", "TestCo")
    
    assert result == {"Why this company?": "Because I love automation."}

# Task 4 — Test Error Handling & Hallucinations
@patch("backend.services.profile_rag.get_llm_client")
@patch("backend.services.profile_rag.get_model_name", return_value="test-model")
@patch("backend.services.profile_rag.load_profile_file", return_value="fake profile data")
@patch("backend.services.profile_rag.cache_collection", MagicMock())
def test_generate_llm_answers_invalid_json(mock_load, mock_model, mock_getClient):
    mock_client = MagicMock()
    mock_getClient.return_value = mock_client
    
    # Mock LLM hallucinating garbage text
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "I didn't output JSON. Here is a rambling essay instead."
    mock_client.chat.completions.create.return_value = mock_response

    fields = ["Why this company?"]
    result = _generate_llm_answers(fields, "example.com", "TestCo")
    
    # Assert it catches the JSONDecodeError cleanly and falls back
    assert result == {"Why this company?": "Not specified in profile."}

# Task 5 — Test the Public Orchestrator
@patch("backend.services.profile_rag._handle_standard_fields")
@patch("backend.services.profile_rag._generate_llm_answers")
@patch("backend.services.profile_rag._build_fast_path_map")
def test_batch_fill_fields_integration(mock_fast_path_map, mock_llm, mock_standard):
    # Mock the internal calls so we purely test orchestration
    mock_fast_path_map.return_value = {}
    mock_standard.return_value = (
        {"First Name": "TestFirst", "Email": "test@example.com"},
        ["Why this company?", "Describe a challenge"]
    )
    mock_llm.return_value = {
        "Why this company?": "I love automation.",
        "Describe a challenge": "I fixed production."
    }
    
    fields = ["First Name", "Email", "Why this company?", "Describe a challenge"]
    result = batch_fill_fields(fields, job_url="example.com", company="TestCo")
    
    # Assert the orchestrator correctly merges the dicts
    assert result == {
        "First Name": "TestFirst",
        "Email": "test@example.com",
        "Why this company?": "I love automation.",
        "Describe a challenge": "I fixed production."
    }
