import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from pathlib import Path
from backend.main import app
from fastapi.responses import FileResponse

# We create the TestClient inside a fixture to prevent global initialization side effects
from backend.services.db_tracker import _ensure_db

@pytest.fixture
def client(tmp_path):
    with patch("backend.services.db_tracker.DB_PATH", tmp_path / "test_tracker.db"), \
         patch("backend.services.profile_rag.cache_collection", MagicMock()), \
         patch("backend.services.excel_formatter.EXCEL_PATH", tmp_path / "test_excel.xlsx"):

        # Ensure tables are created for the temporary test database
        _ensure_db()

        with TestClient(app) as c:
            yield c

# ====================
# Scout Router Tests
# ====================

@patch("backend.routers.scout.processor.process_jobs_bg")
@patch("backend.routers.scout.fetch_simplify_jobs")
@patch("backend.routers.scout.get_job_by_id")
@patch("backend.services.db_tracker.add_job")
def test_scout_run(mock_add, mock_get_job, mock_fetch, mock_bg, client):
    """
    Test POST /api/scout/run returns correct shape
    {found, new, message}
    """
    mock_fetch.return_value = [
        {"job_id": "job_101", "title": "SWE", "company": "TestA"},
        {"job_id": "job_102", "title": "SWE", "company": "TestB"}
    ]

    def side_effect_get_job(job_id):
        if job_id == "job_101":
            return {"job_id": "job_101", "status": "found"}
        return None

    mock_get_job.side_effect = side_effect_get_job
    mock_add.return_value = True

    response = client.post("/api/scout/run")

    assert response.status_code == 200
    data = response.json()
    assert data["found"] == 2
    assert data["new"] == 1
    assert "message" in data

# ====================
# Tracker Router Tests
# ====================

@patch("backend.routers.tracker.get_stats")
def test_tracker_stats(mock_get_stats, client):
    """
    Test GET /api/tracker/stats returns all status keys
    """
    mock_get_stats.return_value = {
        "found": 10, "shortlisted": 5, "tailored": 0,
        "applied": 2, "interviewing": 1, "rejected": 4,
        "offer": 0, "skipped": 2, "failed": 0, "total": 24
    }

    response = client.get("/api/tracker/stats")

    assert response.status_code == 200
    data = response.json()
    assert "found" in data
    assert "shortlisted" in data
    assert "rejected" in data
    assert "total" in data

@patch("backend.routers.tracker.update_job")
def test_tracker_patch_status(mock_update_job, client):
    """
    Test PATCH /api/tracker/{job_id}/status updates correctly
    """
    mock_update_job.return_value = True

    response = client.patch(
        "/api/tracker/job_201/status",
        json={"status": "shortlisted", "notes": "Looks good"}
    )

    assert response.status_code == 200
    assert response.json() == {"updated": True}
    mock_update_job.assert_called_once_with("job_201", status="shortlisted", notes="Looks good")

def test_tracker_export(client, tmp_path):
    """
    Test GET /api/tracker/export returns CSV content.
    Since EXCEL_PATH is mocked in the fixture, we can create a dummy file there to test successful download.
    """
    excel_path = tmp_path / "test_excel.xlsx"
    excel_path.write_text("dummy csv data") # Creating dummy data

    with patch("backend.routers.tracker.EXCEL_PATH", excel_path):
        response = client.get("/api/tracker/export")
        assert response.status_code == 200
        # Check that it returns what we wrote
        assert response.content == b"dummy csv data"

# ====================
# Tailor Router Tests
# ====================

@patch("backend.routers.tailor.get_job_by_id")
@patch("backend.routers.tailor.get_jobs")
@patch("backend.routers.tailor.load_job_details")
def test_tailor_missing_job(mock_load, mock_get_jobs, mock_get_job_by_id, client):
    """
    Test POST /api/tailor/{job_id} returns 404 for missing job
    """
    mock_get_job_by_id.return_value = None
    mock_get_jobs.return_value = []

    response = client.post("/api/tailor/single/job_missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "Job not found in tracking DB"}

@patch("backend.routers.tailor.get_job_by_id")
@patch("backend.routers.tailor.load_job_details")
@patch("backend.routers.tailor.get_settings")
def test_tailor_low_score_400(mock_get_settings, mock_load, mock_get_job_by_id, client):
    """
    Test POST /api/tailor/single/{job_id} returns 400 if score below threshold
    """
    mock_get_settings.return_value = {"score_threshold": 6}

    mock_get_job_by_id.return_value = {
        "job_id": "job_low_score",
        "status": "shortlisted",
        "score": 4
    }

    mock_load.return_value = {"description": "Basic requirements"}

    response = client.post("/api/tailor/single/job_low_score")
    assert response.status_code == 400
    assert response.json() == {"detail": "Job score below threshold"}
