import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from backend.services.resume_tailor import (
    _inject_content_into_tex,
    _compile_latex_to_pdf,
    run_tailor
)

# Task 2 — Test the String Injector (No Mocks Needed)
def test_inject_content_into_tex():
    template_str = "\\begin{document}\n%% BEGIN SUMMARY %%\nold text\n%% END SUMMARY %%\n\\end{document}"
    
    # Mocking the dictionary output of `parse_marker_sections` for this basic string
    sections = {
        "SUMMARY": {
            "start": 1,
            "end": 3,
            "content": "old text"
        }
    }
    
    tailored_content = {"SUMMARY": "Brand new tailored summary."}
    
    result = _inject_content_into_tex(template_str, tailored_content, sections)
    
    expected = "\\begin{document}\n%% BEGIN SUMMARY %%\nBrand new tailored summary.\n%% END SUMMARY %%\n\\end{document}"
    
    assert result == expected

# Task 3 — Test the OS Compiler (Fully Mocked)
@patch("backend.services.resume_tailor.subprocess.run")
@patch("backend.services.resume_tailor.pypdf.PdfReader")
@patch("backend.services.resume_tailor.Path.exists")
@patch("builtins.open", new_callable=MagicMock)
def test_compile_latex_to_pdf(mock_open, mock_exists, mock_pdf_reader, mock_run):
    # Setup mocks
    mock_run.return_value = MagicMock(stdout="Mocked compilation output")
    mock_exists.return_value = True  # Pretend the PDF compilation produced a file
    
    # Mock page count logic to return exactly 1 page
    mock_reader_instance = MagicMock()
    mock_reader_instance.pages = ["page1"]
    mock_pdf_reader.return_value = mock_reader_instance
    
    output_dir = Path("/mock/dir")
    filename = "resume"
    tex_string = "LaTex Code Here"
    
    # We patch write_text and cleanup to avoid actually touching the local disk
    with patch("backend.services.resume_tailor.Path.write_text"):
        with patch("backend.services.resume_tailor._cleanup_aux_files"):
            result = _compile_latex_to_pdf(tex_string, output_dir, filename)
    
    # Assert that subprocess.run was correctly dispatched 
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    # The first argument should be the list: ["pdflatex", "-jobname=resume", ...]
    cmd_list = args[0]
    assert "pdflatex" in cmd_list
    assert "-jobname=resume" in cmd_list
    assert "-interaction=nonstopmode" in cmd_list
    
    # Assert return object
    assert result["status"] == "success"
    assert result["output_dir"] == str(output_dir)
    assert result["pdf_path"] == str(output_dir / "resume.pdf")

# Task 4 — Test the Orchestrator Pipeline
@patch("backend.services.resume_tailor.get_settings")
@patch("backend.services.resume_tailor.load_references")
@patch("backend.services.resume_tailor.parse_marker_sections")
@patch("builtins.open", new_callable=MagicMock)
@patch("backend.services.resume_tailor.json.dump")
@patch("backend.services.resume_tailor._generate_tailored_content")
@patch("backend.services.resume_tailor._inject_content_into_tex")
@patch("backend.services.resume_tailor._compile_latex_to_pdf")
def test_run_tailor_pipeline(
    mock_compile, mock_inject, mock_generate,
    mock_json_dump, mock_open,
    mock_parse_sections, mock_load_refs, mock_get_settings, tmp_path
):
    # Patch OUTPUT_DIR dynamically with the pytest tmp_path
    with patch("backend.services.resume_tailor.OUTPUT_DIR", tmp_path):
        # Base setup
        mock_get_settings.return_value = {"candidate_name": "Suyesh Jadhav"}
        mock_load_refs.return_value = {
            "base_resume_tex": "base tex",
            "context_bank": {}
        }
        mock_parse_sections.return_value = {}
        
        # Pipeline stages mocks
        mock_generate.return_value = {"SUMMARY": "New Summary"}
        mock_inject.return_value = "injected tex output"
        
        mock_compile.return_value = {
            "status": "success", 
            "output_dir": str(tmp_path / "TestCompany-Software_Engineer-2026-03-04"), 
            "pdf_path": str(tmp_path / "TestCompany-Software_Engineer-2026-03-04" / "resume.pdf")
        }
        
        # Execution
        job = {
            "title": "Software Engineer",
            "company": "TestCompany",
            "description": "Needs basic python."
        }
        
        # Patch CUSTOM_COMMANDS with a fake path so that .exists() naturally returns False
        with patch("backend.services.resume_tailor.CUSTOM_COMMANDS", tmp_path / "fake-custom-commands.tex"):
            result = run_tailor(job)
        
        # Assert sequence constraints
        mock_generate.assert_called_once()
        mock_inject.assert_called_once()
        mock_compile.assert_called_once()
        
        # Assert the exact contract was returned
        assert result == {
            "status": "success", 
            "output_dir": str(tmp_path / "TestCompany-Software_Engineer-2026-03-04"), 
            "pdf_path": str(tmp_path / "TestCompany-Software_Engineer-2026-03-04" / "resume.pdf")
        }

