from pathlib import Path
from unittest.mock import MagicMock, patch
import pypdf

from backend.services.resume_tailor import (
    _compile_latex_to_pdf,
    _sanitize_tailored_content,
    _sanitize_tex_string,
    _validate_generated_resume_artifacts,
    run_tailor,
)
from backend.utils.latex_parser import inject_content_into_tex

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

    result = inject_content_into_tex(template_str, tailored_content, sections)

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


def test_sanitize_tailored_content_removes_forbidden_phrases_and_tags():
    raw = {
        "EXPERIENCE: Test": (
            "\\bitem{Built analytics workflows. \\textbf{(improving research)}}\n"
            "\\bitem{Shipped dashboards. \\textbf{(Full Stack Development)}}\n"
            "\\bitem{Delivered platform update. [your stack: e.g., React, Node.js, MySQL]}\n"
            "\\bitem{Integrated orchestration \\textbf{(using Python, GitHub Copilot)} in services}"
        ),
        "SKILLS": "\\textbf{Languages:} Python, Go",
    }

    cleaned = _sanitize_tailored_content(raw)
    cleaned_exp = cleaned["EXPERIENCE: Test"]

    assert "improving research" not in cleaned_exp.lower()
    assert "(Full Stack Development)" not in cleaned_exp
    assert "[your stack:" not in cleaned_exp.lower()
    assert "(using python" not in cleaned_exp.lower()
    assert "\\bitem{Built analytics workflows." in cleaned_exp
    assert "\\bitem{Shipped dashboards." in cleaned_exp


def test_sanitize_tex_string_removes_forbidden_phrase_from_final_tex():
    tex = "\\bitem{Owned platform delivery. \\textbf{(improving research)} [e.g., React, Node.js] \\textbf{(using Python)}}"
    cleaned = _sanitize_tex_string(tex)
    assert "improving research" not in cleaned.lower()
    assert "[e.g.," not in cleaned.lower()
    assert "(using python" not in cleaned.lower()
    assert "\\bitem{Owned platform delivery." in cleaned


def test_sanitize_tailored_content_enforces_strong_ownership_language():
    raw = {
        "PROJECTS": (
            "\\bitem{Assist in building and maintaining a ReAct system with voice IO}\n"
            "\\bitem{helped build an internal retrieval workflow}\n"
            "\\bitem{Supported the development of automation checks}"
        )
    }

    cleaned = _sanitize_tailored_content(raw)["PROJECTS"]
    lowered = cleaned.lower()
    assert "assist in building and maintaining" not in lowered
    assert "helped build" not in lowered
    assert "supported the development of" not in lowered
    assert "\\bitem{Built and maintained" in cleaned
    assert "\\bitem{Built an internal retrieval workflow}" in cleaned
    assert "\\bitem{Developed automation checks}" in cleaned


def test_sanitize_tailored_content_fixes_contribute_participated_engaged_patterns():
    raw = {
        "PROJECTS": (
            "\\bitem{Contribute to a fully independent ReAct reasoning system from scratch}\\n"
            "\\bitem{Develop a 6-tool deterministic ReAct agent runtime}\\n"
            "\\bitem{Document and maintain a dual-storage memory and caching system}\\n"
            "\\bitem{A \\textbf{contribute to} 8-stage asynchronous processing pipeline}\\n"
            "\\bitem{Participated in decorator-based auto-registration workflows}\\n"
            "\\bitem{Engaged in hybrid plagiarism structure logic}"
        )
    }

    cleaned = _sanitize_tailored_content(raw)["PROJECTS"]
    lowered = cleaned.lower()

    assert "contribute to" not in lowered
    assert "develop a 6-tool" not in lowered
    assert "document and maintain" not in lowered
    assert "participated in" not in lowered
    assert "engaged in" not in lowered

    assert "\\bitem{Built a fully independent ReAct reasoning system from scratch}" in cleaned
    assert "\\bitem{Developed a 6-tool deterministic ReAct agent runtime}" in cleaned
    assert "\\bitem{Documented and maintained a dual-storage memory and caching system}" in cleaned
    assert "\\bitem{Developed 8-stage asynchronous processing pipeline}" in cleaned
    assert "\\bitem{Developed decorator-based auto-registration workflows}" in cleaned
    assert "\\bitem{Developed hybrid plagiarism structure logic}" in cleaned


def test_validate_generated_resume_artifacts_warns_on_rule_violations(tmp_path):
    output_dir = tmp_path / "generated"
    output_dir.mkdir(parents=True, exist_ok=True)

    tex = r"""
\section{Projects}
\bulletListStart
\bitem{A contributed to \\textbf{Rust} modules [your stack: e.g., React, Node.js, MySQL] and handled 999 records with a very long sentence that keeps going to exceed the character limit substantially for deterministic validation checks.}
\bulletListEnd
""".strip()
    (output_dir / "resume.tex").write_text(tex, encoding="utf-8")

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(output_dir / "resume.pdf", "wb") as f:
        writer.write(f)

    context_bank = {
        "project": [
            {
                "name": "Demo",
                "bullet_1": [
                    {
                        "tools_used": "Python, FastAPI",
                        "metric": "Processed 100 records"
                    }
                ]
            }
        ]
    }

    warnings = _validate_generated_resume_artifacts(output_dir, context_bank)

    assert any("[placeholder]" in warning for warning in warnings)
    assert any("[ownership]" in warning for warning in warnings)
    assert any("[action_verb]" in warning for warning in warnings)
    assert any("[numbers]" in warning for warning in warnings)
    assert any("[tools]" in warning for warning in warnings)
    assert any("[length]" in warning for warning in warnings)
    # nouns validator removed — false positives on common English words

# Task 4 — Test the Orchestrator Pipeline


@patch("backend.services.resume_tailor._validate_generated_resume_artifacts", return_value=[])
@patch("backend.services.resume_tailor.get_settings")
@patch("backend.services.resume_tailor.load_references")
@patch("backend.services.resume_tailor.parse_marker_sections")
@patch("builtins.open", new_callable=MagicMock)
@patch("backend.services.resume_tailor.json.dump")
@patch("backend.services.resume_tailor.generate_tailored_content")
@patch("backend.services.resume_tailor.extract_jd_keywords")
@patch("backend.services.resume_tailor.build_ranked_projects_section")
@patch("backend.services.resume_tailor.inject_content_into_tex")
@patch("backend.services.resume_tailor._compile_latex_to_pdf")
@patch("backend.services.db_tracker._get_readable_job_dir")
def test_run_tailor_pipeline(
    mock_get_dir,
    mock_compile,
    mock_inject,
    mock_ranked_projects,
    mock_extract_keywords,
    mock_generate,
    mock_json_dump,
    mock_open,
    mock_parse_sections,
    mock_load_refs,
    mock_get_settings,
    mock_validate,
    tmp_path,
):
    mock_get_dir.return_value = tmp_path / "TestCompany-Software_Engineer-2026-03-04"

    mock_get_settings.return_value = {"candidate_name": "Suyesh Jadhav"}
    mock_load_refs.return_value = {
        "base_resume_tex": "base tex", "context_bank": {}}
    mock_parse_sections.return_value = {}
    mock_extract_keywords.return_value = {
        "required_skills": ["python"],
        "required_tools": [],
        "action_verbs": [],
        "seniority_signals": [],
        "domain_focus": [],
    }

    mock_generate.return_value = {
        "SUMMARY": "New Summary",
        "EXPERIENCE: TestCompany": "\\bitem{Built systems. \\textbf{(improving research)}}",
    }
    mock_ranked_projects.return_value = ("\\section{Projects}\n\\outerListStart\n\\outerListEnd\n", {
        "selected_projects": ["P1", "P2", "P3"],
        "ranked": [],
        "keywords": {},
    })
    mock_inject.return_value = "injected tex output"
    mock_compile.return_value = {
        "status": "success",
        "output_dir": str(tmp_path / "TestCompany-Software_Engineer-2026-03-04"),
        "pdf_path": str(tmp_path / "TestCompany-Software_Engineer-2026-03-04" / "resume.pdf"),
    }

    job = {
        "title": "Software Engineer",
        "company": "TestCompany",
        "description": "Needs basic python.",
    }

    result = run_tailor(job)

    mock_generate.assert_called_once()
    mock_inject.assert_called_once()
    mock_compile.assert_called_once()
    mock_validate.assert_called_once()

    inject_kwargs = mock_inject.call_args.kwargs
    injected_content = inject_kwargs["tailored_content"]
    assert "improving research" not in injected_content["EXPERIENCE: TestCompany"].lower(
    )

    compile_kwargs = mock_compile.call_args.kwargs
    compile_content = compile_kwargs["tailored_content"]
    assert "improving research" not in compile_content["EXPERIENCE: TestCompany"].lower(
    )

    assert result["status"] == "success"
    assert result["output_dir"] == str(
        tmp_path / "TestCompany-Software_Engineer-2026-03-04"
    )
    assert result["pdf_path"] == str(
        tmp_path / "TestCompany-Software_Engineer-2026-03-04" / "resume.pdf"
    )
    assert "tailor_timings" in result
