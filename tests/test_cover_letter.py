import base64
from pathlib import Path
from unittest.mock import patch

from backend.routers.tailor import GenerateRequest, generate_cover_letter
from backend.services.cover_letter import clean_llm_cover_letter, run_cover_letter


def test_run_cover_letter_writes_expected_filename(tmp_path):
    job = {
        "job_id": "abc12345",
        "company": "TestCo",
        "title": "Software Engineer Intern",
        "description": "A" * 400,
    }

    refs = {
        "candidate_profile": "Candidate profile",
        "cover_letter_tone": "Template",
        "cover_letter_tex_template": "",
        "context_bank": {},
    }

    with patch("backend.services.cover_letter._get_readable_job_dir", return_value=tmp_path):
        with patch("backend.services.cover_letter.load_references", return_value=refs):
            with patch(
                "backend.services.cover_letter.generate_cover_letter_content",
                return_value="Dear Team,\n\nThis is a generated letter.\n\nRegards,\nCandidate",
            ):
                result = run_cover_letter(job)

    assert result["status"] == "success"
    assert Path(result["cover_letter_path"]).name == "cover letter.md"
    assert Path(result["cover_letter_path"]).exists()


def test_generate_cover_letter_endpoint_returns_base64_for_existing_file(tmp_path):
    letter_path = tmp_path / "cover letter.md"
    letter_content = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
    letter_path.write_text(letter_content, encoding="utf-8")

    with patch("backend.routers.tailor._resolve_job", return_value={"job_id": "job-1"}):
        with patch(
            "backend.routers.tailor._load_or_scrape_description",
            return_value={"job_id": "job-1", "description": "A" * 200},
        ):
            with patch("backend.routers.tailor._find_existing_file_for_job", return_value=letter_path):
                with patch("backend.routers.tailor.run_cover_letter") as mock_run_cover:
                    response = generate_cover_letter(
                        GenerateRequest(job_id="job-1"))

    assert response["job_id"] == "job-1"
    assert response["filename"] == "cover letter.md"
    decoded = base64.b64decode(response["cover_letter_base64"]).decode("utf-8")
    assert decoded.replace("\r\n", "\n") == letter_content
    mock_run_cover.assert_not_called()


def test_clean_llm_cover_letter_removes_headers_and_signature_lines():
    raw = """Suyesh Jadhav
+1-984-382-2189 | smjadha2@ncsu.edu
March 16, 2026

Hiring Team
{{COMPANY}}

RE: {{ROLE}}

Dear Hiring Manager,

I built a retrieval pipeline that reduced response latency by 32% while improving answer quality.

I also built CI automation for model evaluation and accelerated experiment throughput.

Thank you for your time.

Best regards,
Suyesh Jadhav
"""

    cleaned = clean_llm_cover_letter(raw, company_name="Acme")

    assert "Dear Hiring Manager" not in cleaned
    assert "Best regards" not in cleaned
    assert "Suyesh Jadhav" not in cleaned
    assert "RE:" not in cleaned
    assert "@ncsu.edu" not in cleaned
    assert "retrieval pipeline" in cleaned


def test_clean_llm_cover_letter_strips_code_fences_and_markdown():
    raw = """```markdown
# Cover Letter

- Built production ETL pipelines for analytics and model training.
1. Improved onboarding metrics by instrumenting funnel experiments.
```
"""

    cleaned = clean_llm_cover_letter(raw, company_name="Stripe")

    assert "```" not in cleaned
    assert "#" not in cleaned
    assert "- " not in cleaned
    assert "1." not in cleaned
    assert "Built production ETL pipelines" in cleaned


def test_clean_llm_cover_letter_strips_conversational_preamble_and_placeholder():
    raw = """Certainly! Here's a tailored cover letter for the role:

I built automation workflows for BOM data quality and reduced manual review steps.

I can bring the same ownership to Lenovo's Software Engineer Intern role. [Your Name]
"""

    cleaned = clean_llm_cover_letter(raw, company_name="Lenovo")

    assert "Certainly" not in cleaned
    assert "tailored cover letter" not in cleaned.lower()
    assert "[Your Name]" not in cleaned
    assert "automation workflows" in cleaned


def test_clean_llm_cover_letter_strips_false_company_claims():
    raw = """My experience developing practical tools like BOM data analysis systems at Lenovo would be instrumental.
    During my work at Lenovo, I leveraged advanced Excel functions to automate workflows.
    Additionally, my recent project involving BOM data analysis at Lenovo aligned with requirements.
    This work at Lenovo improved accuracy and governance of BOM-related tasks.
    """

    cleaned = clean_llm_cover_letter(raw, company_name="Lenovo")

    assert "at Lenovo" not in cleaned.lower()
    assert "during my work at lenovo" not in cleaned.lower()
    assert "at the company" not in cleaned.lower()
    assert "BOM data analysis systems" in cleaned
    assert "advanced Excel functions" in cleaned


def test_clean_llm_cover_letter_strips_fictional_projects():
    raw = """My work developing an automated Pokémon battle simulator using Java and Java Swing helped optimize systems. 
    Similarly, by analyzing patterns in Pokémon battles, I was able to streamline logic. 
    My recent project involving a Mario game engine aligned with requirements.
    However, my experience with TweetScape's NLP pipeline and WolfCafe+ backend work is directly applicable."""

    # Create a minimal context_bank with valid projects
    context_bank = {
        "project": [
            {"name": "TweetScape", "tools_used": "React, FastAPI, NLP"},
            {"name": "WolfCafe+", "tools_used": "React, Node.js, MongoDB"},
        ]
    }

    cleaned = clean_llm_cover_letter(raw, context_bank=context_bank)

    # Fictional projects should be removed
    assert "Pokémon" not in cleaned.lower()
    assert "pokemon" not in cleaned.lower()
    assert "Mario game engine" not in cleaned

    # Real projects should remain
    assert "TweetScape" in cleaned
    assert "WolfCafe+" in cleaned


def test_run_cover_letter_normalizes_swapped_company_and_title(tmp_path):
    job = {
        "job_id": "abc12345",
        "company": "75124",
        "title": "Lenovo",
        "description": "Skip to content\nLenovo\nSoftware Engineer Intern - Summer 2026\nGeneral Information",
        "apply_link": "https://jobs.lenovo.com/en_US/careers/JobDetail/Intern-Software-Engineer-Summer-2026/75124",
    }

    refs = {
        "candidate_profile": "Candidate profile",
        "cover_letter_tone": "Template",
        "cover_letter_tex_template": "",
        "context_bank": {},
    }

    with patch("backend.services.cover_letter._get_readable_job_dir", return_value=tmp_path):
        with patch("backend.services.cover_letter.load_references", return_value=refs):
            with patch(
                "backend.services.cover_letter.generate_cover_letter_content",
                return_value="Built relevant systems and can contribute quickly.",
            ) as mock_generate:
                result = run_cover_letter(job)

    assert result["status"] == "success"
    kwargs = mock_generate.call_args.kwargs
    assert kwargs["company"] == "Lenovo"
    assert kwargs["role"].startswith("Software Engineer Intern")
