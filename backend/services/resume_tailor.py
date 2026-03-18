import json
import re
import shutil
import subprocess
import pypdf
from datetime import datetime
from pathlib import Path

from backend.services.llm_client import get_settings
from backend.utils.latex_parser import (
    parse_marker_sections,
    inject_content_into_tex,
    cleanup_latex_aux_files
)
from backend.utils.text_cleaner import safe_filename
from backend.utils.reference_loader import load_references
from backend.utils.latex_utils import (
    _sanitize_tex_string,
    _sanitize_tailored_content,
)
from backend.services.bullet_validator import (
    _validate_generated_resume_artifacts,
)
from backend.services.fact_selector import (
    _build_deterministic_experience_section,
    _rewrite_weak_project_bullets_deterministically,
)
from backend.services.resume_generators import (
    extract_jd_keywords,
    generate_tailored_content,
    trim_bullets,
    build_ranked_projects_section,
)

ROOT_DIR = Path(__file__).parent.parent.parent
OUTPUT_DIR = ROOT_DIR / "outputs" / "applications"

DETERMINISTIC_SECTIONS = {
    "PROJECTS",
    "EXPERIENCE",
}


def _extract_projects_body(tex_string: str) -> tuple[int, int, str] | None:
    match = re.search(
        r"\\section\{Projects\}(?P<body>.*?)(?=\\section\{Experience\})",
        tex_string,
        flags=re.DOTALL,
    )
    if not match:
        return None
    return match.start("body"), match.end("body"), match.group("body")


def _replace_experience_section(tex_string: str, experience_section_tex: str) -> str:
    pattern = re.compile(
        r"\\section\{Experience\}.*?(?=\\end\{document\})",
        re.DOTALL,
    )
    return pattern.sub(lambda _m: experience_section_tex + "\n", tex_string)


def _cleanup_aux_files(output_dir: Path, filename: str):
    """Internal helper to remove LaTeX auxiliary files after compilation."""
    cleanup_latex_aux_files(output_dir, filename)


def _replace_projects_section(tex_string: str, projects_section_tex: str) -> str:
    pattern = re.compile(
        r"\\section\{Projects\}.*?(?=\\section\{Experience\})",
        re.DOTALL,
    )
    return pattern.sub(lambda _m: projects_section_tex + "\n", tex_string)


def _tighten_projects_bullets(tex_string: str, max_items_per_project: int = 2) -> str:
    section_match = re.search(
        r"(?P<projects>\\section\{Projects\}.*?)(?P<next>\\section\{Experience\})",
        tex_string,
        flags=re.DOTALL,
    )
    if not section_match:
        return tex_string

    projects = section_match.group("projects")

    def _trim_block(match: re.Match) -> str:
        body = match.group(1)
        lines = body.splitlines()
        kept = []
        item_count = 0
        for line in lines:
            if "\\bitem{" in line:
                item_count += 1
                if item_count > max_items_per_project:
                    continue
            kept.append(line)
        return "\\bulletListStart\n" + "\n".join(kept) + "\n  \\bulletListEnd"

    projects_tightened = re.sub(
        r"\\bulletListStart\n(.*?)\n\s*\\bulletListEnd",
        _trim_block,
        projects,
        flags=re.DOTALL,
    )

    return tex_string[:section_match.start("projects")] + projects_tightened + tex_string[section_match.start("next"):]


def _compile_latex_to_pdf(tex_string: str, output_dir: Path, filename: str,
                          sections: dict = None, tailored_content: dict = None, template_str: str = None) -> dict:
    """
    Orchestrates the LaTeX to PDF compilation process via pdflatex.

    Includes a 2-pass 'shrink-to-fit' logic:
    1. Trims bullets from experience/projects if they are too long.
    2. Compresses LaTeX vertical spacing (itemsep) and font size slightly.

    Args:
        tex_string (str): The LaTeX content to compile.
        output_dir (Path): Where to save the output files.
        filename (str): Base filename for the PDF.
        sections (dict, optional): Parsed marker sections for granular trimming.
        tailored_content (dict, optional): The raw tailored text blocks.
        template_str (str, optional): The original base template.

    Returns:
        dict: { status: 'success'|'warning'|'error', pdf_path: str, ... }
    """
    tex_path = output_dir / "resume.tex"
    pdf_path = output_dir / f"{filename}.pdf"

    tex_string = _sanitize_tex_string(tex_string)
    tex_path.write_text(tex_string, encoding="utf-8")

    def call_pdflatex():
        """Helper to invoke the pdflatex subprocess."""
        return subprocess.run(
            ["pdflatex", f"-jobname={filename}", "-interaction=nonstopmode",
                "-output-directory", str(output_dir), str(tex_path)],
            capture_output=True, text=True, timeout=60
        )

    def get_page_count():
        """Helper to determine the number of pages in the generated PDF."""
        try:
            with open(pdf_path, "rb") as f:
                reader = pypdf.PdfReader(f)
                return len(reader.pages)
        except Exception:
            return 0

    try:
        pid = call_pdflatex()
        if not pdf_path.exists():
            return {"status": "error", "error": f"PDF compilation failed: {pid.stdout[-500:]}"}

        pages = get_page_count()
        if pages == 1:
            _cleanup_aux_files(output_dir, filename)
            return {"status": "success", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}

        # --- Recovery Pass 1: Bullet Trimming ---
        if tailored_content and sections and template_str:
            print("[TAILOR] Pages > 1. Attempt 1: Trimming bullets...")
            trimmed_rewritten = {}
            for sec, text in tailored_content.items():
                if sec.upper() not in ("SUMMARY", "SKILLS"):
                    trimmed_rewritten[sec] = trim_bullets(text)
                else:
                    trimmed_rewritten[sec] = text

            tailored_tex_trimmed = inject_content_into_tex(
                template_str, trimmed_rewritten, sections)
            tailored_tex_trimmed = _sanitize_tex_string(tailored_tex_trimmed)
            tex_path.write_text(tailored_tex_trimmed, encoding="utf-8")
            call_pdflatex()

            if pdf_path.exists() and get_page_count() == 1:
                _cleanup_aux_files(output_dir, filename)
                return {"status": "success", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}

            tex_string = tailored_tex_trimmed  # Carry trimmed result to next attempt

        # --- Recovery Pass 1.5: Project Density Tightening ---
        print("[TAILOR] Pages > 1. Attempt 1.5: Tightening project bullets...")
        tightened_projects_tex = _tighten_projects_bullets(
            tex_string, max_items_per_project=2)
        tightened_projects_tex = _sanitize_tex_string(tightened_projects_tex)
        tex_path.write_text(tightened_projects_tex, encoding="utf-8")
        call_pdflatex()
        if pdf_path.exists() and get_page_count() == 1:
            _cleanup_aux_files(output_dir, filename)
            return {"status": "success", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}

        tex_string = tightened_projects_tex

        # --- Recovery Pass 2: Layout Compression ---
        print("[TAILOR] Pages > 1. Attempt 2: LaTeX compression...")
        compressed_tex = tex_string.replace(
            r"\setlength{\itemsep}{1pt}", r"\setlength{\itemsep}{0pt}")
        compressed_tex = compressed_tex.replace(r"10pt", r"9.5pt")
        compressed_tex = _sanitize_tex_string(compressed_tex)
        tex_path.write_text(compressed_tex, encoding="utf-8")
        call_pdflatex()

        if pdf_path.exists() and get_page_count() == 1:
            _cleanup_aux_files(output_dir, filename)
            return {"status": "success", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}

        # Final state - still > 1 page
        _cleanup_aux_files(output_dir, filename)
        print("[WARN] Resume is 2 pages. Manual review recommended.")
        return {"status": "warning", "warning": "Resume is 2 pages. Manual review needed.", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}

    except FileNotFoundError:
        return {"status": "error", "error": "pdflatex is not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_tailor(job: dict) -> dict:
    """
    The main high-level pipeline for tailoring a resume.

    Workflow:
    1. Resolve directories and filenames.
    2. Sync job details to a local JSON file for the application folder.
    3. Delegate content generation to the LLM-driven 'resume_generators' service.
    4. Inject generated text into markers using the 'latex_parser' utility.
    5. Compile to PDF with automatic length management.
    6. Perform directory cleanup for consistency.

    Args:
        job (dict): Expected to contain 'company', 'title', 'description', 
                   and optionally 'job_id' and 'strategy'.

    Returns:
        dict: Compilation result including PDF path or error details.
    """
    settings = get_settings()
    candidate_name = settings.get("candidate_name", "Suyesh Jadhav")
    safe_name = safe_filename(candidate_name)

    from backend.services.db_tracker import _get_readable_job_dir

    target_dir = _get_readable_job_dir(job)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Export job details json
    job["tailored_at"] = datetime.now().isoformat()
    with open(target_dir / "job_details.json", "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

    # Clean legacy UUID folder if it exists
    job_id = job.get("job_id")
    if job_id:
        legacy_dir = OUTPUT_DIR / job_id
        if legacy_dir.exists() and legacy_dir.is_dir() and legacy_dir != target_dir:
            try:
                shutil.rmtree(legacy_dir)
            except Exception:
                pass

    refs = load_references()
    sections = parse_marker_sections(refs["base_resume_tex"])

    # Extract JD keywords once — shared across content generation and project ranking.
    _jd_desc = job.get("description", "")
    if len(_jd_desc) > 8000:
        _jd_desc = _jd_desc[:8000]
    jd_keywords = extract_jd_keywords(_jd_desc)

    # Step 1: Generate Tailored Content via LLM service
    content = generate_tailored_content(
        job_description=_jd_desc,
        sections=sections,
        context_bank=refs["context_bank"],
        strategy=job.get("strategy", "full_rewrite"),
        keywords=jd_keywords,
    )
    content = _sanitize_tailored_content(content)

    # Build a ranked projects section from context_bank and replace static template ordering.
    projects_section_tex, ranking_diagnostics = build_ranked_projects_section(
        job_description=_jd_desc,
        context_bank=refs["context_bank"],
        strategy=job.get("strategy", "full_rewrite"),
        keywords=jd_keywords,
    )

    # Step 2: Inject Content into LaTeX template
    tex_str = inject_content_into_tex(
        template_str=refs["base_resume_tex"],
        tailored_content=content,
        sections=sections
    )
    tex_str = _replace_projects_section(tex_str, projects_section_tex)

    # Phase 2/3 deterministic routing.
    if settings.get("deterministic_project_bullets", False):
        if "PROJECTS" in DETERMINISTIC_SECTIONS:
            tex_str, fallback_events = _rewrite_weak_project_bullets_deterministically(
                tex_str,
                refs["base_resume_tex"],
                refs["context_bank"],
            )
            job["deterministic_rewrite_fallbacks"] = fallback_events

        if "EXPERIENCE" in DETERMINISTIC_SECTIONS:
            exp_section_tex, exp_diagnostics = _build_deterministic_experience_section(
                refs["context_bank"],
                jd_keywords,
            )
            tex_str = _replace_experience_section(tex_str, exp_section_tex)
            job["experience_deterministic_ranking"] = exp_diagnostics

    # Persist diagnostics for reproducibility/debugging.
    job["project_ranking"] = ranking_diagnostics
    with open(target_dir / "job_details.json", "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

    # Step 3: Compile PDF and handle multi-page retry flow
    pdf_res = _compile_latex_to_pdf(
        tex_string=tex_str,
        output_dir=target_dir,
        filename=safe_name,
        sections=sections,
        tailored_content=content,
        template_str=refs["base_resume_tex"]
    )

    # Phase 1 validation: warn_only mode. Preserve output and persist warnings.
    validation_warnings = _validate_generated_resume_artifacts(
        target_dir, refs["context_bank"]
    )
    job["validation_warnings"] = validation_warnings
    with open(target_dir / "job_details.json", "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

    if validation_warnings:
        pdf_res["validation_warnings"] = validation_warnings

    return pdf_res


if __name__ == "__main__":
    # Simple smoke test
    print(safe_filename("Suyesh Jadhav"))
