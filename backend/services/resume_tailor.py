import json
import time
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
    _extract_bitem_payload_spans,
    _visible_text_from_latex,
    _escape_latex_inline,
    _trim_visible_text_to_limit,
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


def _load_references_from_dir(refs_dir: Path) -> dict:
    """
    Load references from a specific directory instead of REFERENCES_DIR.
    Used for remote/override workflows.
    """
    import tomllib

    base_tex = (refs_dir / "main.tex").read_text(encoding="utf-8")

    with open(refs_dir / "context_bank.toml", "rb") as f:
        context_bank = tomllib.load(f)

    candidate_profile = (
        refs_dir / "candidate_profile.md").read_text(encoding="utf-8")

    cover_letter_template = ""
    cover_letter_template_path = refs_dir / "cover_letter_template.md"
    if cover_letter_template_path.exists():
        cover_letter_template = cover_letter_template_path.read_text(
            encoding="utf-8")

    cover_letter_tex_template = ""
    cover_letter_tex_path = refs_dir / "cover_letter.tex"
    if cover_letter_tex_path.exists():
        cover_letter_tex_template = cover_letter_tex_path.read_text(
            encoding="utf-8")

    return {
        "base_resume_tex": base_tex,
        "context_bank": context_bank,
        "candidate_profile": candidate_profile,
        "cover_letter_template": cover_letter_template,
        "cover_letter_tone": cover_letter_template,
        "cover_letter_tex_template": cover_letter_tex_template,
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


def _warning_categories(warnings: list[str]) -> set[str]:
    categories = set()
    for warning in warnings:
        match = re.match(r"^\[([^\]]+)\]", str(warning).strip())
        if match:
            categories.add(match.group(1).lower())
    return categories


def _classify_validation_warnings(warnings: list[str]) -> dict:
    fixable = {"ownership", "action_verb", "length"}
    hard = {"nouns", "tools", "numbers"}
    categories = _warning_categories(warnings)
    return {
        "fixable": sorted(categories & fixable),
        "hard": sorted(categories & hard),
        "other": sorted(categories - fixable - hard),
    }


def _trim_long_bullets_deterministically(tex_string: str, max_visible_chars: int = 200) -> str:
    spans = _extract_bitem_payload_spans(tex_string)
    if not spans:
        return tex_string

    updated = tex_string
    for start, end, payload in sorted(spans, key=lambda item: item[0], reverse=True):
        visible = _visible_text_from_latex(payload)
        if len(visible) <= max_visible_chars:
            continue

        trimmed_visible = _trim_visible_text_to_limit(
            visible, max_visible_chars)
        trimmed_visible = trimmed_visible.strip()
        if trimmed_visible and not trimmed_visible.endswith("."):
            trimmed_visible += "."
        replacement = _escape_latex_inline(trimmed_visible)
        updated = updated[:start] + replacement + updated[end:]

    return updated


def _resolve_bullet_section(prefix: str) -> str:
    matches = list(re.finditer(r"\\section\{([^}]*)\}", prefix))
    if not matches:
        return "OTHER"
    section_name = matches[-1].group(1).strip().lower()
    if section_name.startswith("projects"):
        return "PROJECTS"
    if section_name.startswith("experience"):
        return "EXPERIENCE"
    return "OTHER"


def _resolve_project_group(prefix: str) -> str:
    matches = list(
        re.finditer(
            r"\\projectheading.*?\\textbf\{([^}]*)\}", prefix, flags=re.DOTALL)
    )
    if matches:
        return f"PROJECTS: {matches[-1].group(1).strip()}"
    return "PROJECTS: Unknown"


def _resolve_experience_group(prefix: str) -> str:
    matches = list(
        re.finditer(
            r"\\subheading\s*\n\s*\{([^}]*)\}\{[^}]*\}\s*\n\s*\{[^}]*\}\{[^}]*\}",
            prefix,
            flags=re.DOTALL,
        )
    )
    if matches:
        return f"EXPERIENCE: {matches[-1].group(1).strip()}"
    return "EXPERIENCE: Unknown"


def _sectioned_bullet_index(tex_string: str) -> dict[int, dict]:
    spans = _extract_bitem_payload_spans(tex_string)
    if not spans:
        return {}

    counters: dict[tuple[str, str], int] = {}
    mapping: dict[int, dict] = {}
    for global_idx, (start, end, payload) in enumerate(spans, start=1):
        prefix = tex_string[:start]
        section = _resolve_bullet_section(prefix)

        if section == "PROJECTS":
            group = _resolve_project_group(prefix)
        elif section == "EXPERIENCE":
            group = _resolve_experience_group(prefix)
        else:
            group = section

        key = (section, group)
        local_idx = counters.get(key, 0) + 1
        counters[key] = local_idx

        mapping[global_idx] = {
            "global_index": global_idx,
            "section": section,
            "group": group,
            "local_index": local_idx,
            "start": start,
            "end": end,
            "payload": payload,
        }

    return mapping


def _hard_warning_entries(warnings: list[str], mapping: dict[int, dict]) -> list[dict]:
    hard_categories = {"nouns", "tools", "numbers"}
    entries = []
    for warning in warnings:
        match = re.match(r"^\[([^\]]+)\]\s+bullet\s+(\d+):",
                         str(warning).strip(), flags=re.IGNORECASE)
        if not match:
            continue
        category = match.group(1).lower()
        if category in hard_categories:
            idx = int(match.group(2))
            bullet = mapping.get(idx)
            if not bullet:
                continue
            entries.append({
                "category": category,
                "global_index": idx,
                "section": bullet["section"],
                "group": bullet["group"],
                "local_index": bullet["local_index"],
            })
    return entries


def _fallback_bullets_to_source(
    tex_string: str,
    base_tex_string: str,
    warning_entries: list[dict],
) -> str:
    if not warning_entries:
        return tex_string

    current_map = _sectioned_bullet_index(tex_string)
    base_map = _sectioned_bullet_index(base_tex_string)
    if not current_map or not base_map:
        return tex_string

    base_by_key = {
        (entry["section"], entry["group"], entry["local_index"]): entry["payload"]
        for entry in base_map.values()
    }

    replacements = []
    for warning in warning_entries:
        key = (warning["section"], warning["group"], warning["local_index"])
        replacement = base_by_key.get(key)
        current_entry = current_map.get(warning["global_index"])
        if not replacement or not current_entry:
            continue
        replacements.append((
            current_entry["start"],
            current_entry["end"],
            replacement,
        ))

    if not replacements:
        return tex_string

    updated = tex_string
    for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
        updated = updated[:start] + replacement + updated[end:]

    return updated


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


def run_tailor(
    job: dict,
    references_override: Path = None,
    candidate_name: str = None,
    groq_api_key: str = None
) -> dict:
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
        references_override (Path, optional): Load reference files from this directory
                                              instead of default REFERENCES_DIR.
        candidate_name (str, optional): Override candidate name from settings.
        groq_api_key (str, optional): Groq API key to use for this run.
                                       If provided, uses Groq; else falls back to settings.

    Returns:
        dict: Compilation result including PDF path or error details.
    """
    t_pipeline_start = time.perf_counter()
    timings = {}

    settings = get_settings()
    # Use override if provided, else load from settings
    final_candidate_name = candidate_name or settings.get(
        "candidate_name", "Suyesh Jadhav")
    safe_name = safe_filename(final_candidate_name)

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

    t0 = time.perf_counter()
    # Load references from override dir or default
    if references_override:
        refs = _load_references_from_dir(references_override)
    else:
        refs = load_references()
    sections = parse_marker_sections(refs["base_resume_tex"])
    timings["load_references_and_parse"] = round(time.perf_counter() - t0, 3)

    # Extract JD keywords once — shared across content generation and project ranking.
    _jd_desc = job.get("description", "")
    if len(_jd_desc) > 8000:
        _jd_desc = _jd_desc[:8000]

    t0 = time.perf_counter()
    jd_keywords = extract_jd_keywords(_jd_desc)
    timings["extract_jd_keywords"] = round(time.perf_counter() - t0, 3)

    deterministic_experience_ready = False
    prebuilt_experience_section = None
    prebuilt_experience_diagnostics = {}
    if settings.get("deterministic_project_bullets", False) and "EXPERIENCE" in DETERMINISTIC_SECTIONS:
        try:
            candidate_section, candidate_diagnostics = _build_deterministic_experience_section(
                refs["context_bank"],
                jd_keywords,
            )
            if candidate_section and "\\section{Experience}" in candidate_section:
                deterministic_experience_ready = True
                prebuilt_experience_section = candidate_section
                prebuilt_experience_diagnostics = candidate_diagnostics
        except Exception as exc:
            print(
                f"[TAILOR] Deterministic Experience prebuild unavailable; using LLM rewrite path. Error: {exc}")

    job["experience_deterministic_ready"] = deterministic_experience_ready

    # Step 1: Generate Tailored Content via LLM service
    t0 = time.perf_counter()
    content = generate_tailored_content(
        job_description=_jd_desc,
        sections=sections,
        context_bank=refs["context_bank"],
        strategy=job.get("strategy", "full_rewrite"),
        keywords=jd_keywords,
        skip_experience_rewrite=deterministic_experience_ready,
    )
    content = _sanitize_tailored_content(content)
    timings["llm_content_generation"] = round(time.perf_counter() - t0, 3)

    # Build a ranked projects section from context_bank and replace static template ordering.
    t0 = time.perf_counter()
    projects_section_tex, ranking_diagnostics = build_ranked_projects_section(
        job_description=_jd_desc,
        context_bank=refs["context_bank"],
        strategy=job.get("strategy", "full_rewrite"),
        keywords=jd_keywords,
    )
    timings["project_ranking_and_generation"] = round(
        time.perf_counter() - t0, 3)

    # Step 2: Inject Content into LaTeX template
    t0 = time.perf_counter()
    tex_str = inject_content_into_tex(
        template_str=refs["base_resume_tex"],
        tailored_content=content,
        sections=sections
    )
    tex_str = _replace_projects_section(tex_str, projects_section_tex)
    timings["latex_injection"] = round(time.perf_counter() - t0, 3)

    # Phase 2/3 deterministic routing.
    t0 = time.perf_counter()
    if settings.get("deterministic_project_bullets", False):
        if "PROJECTS" in DETERMINISTIC_SECTIONS:
            tex_str, fallback_events = _rewrite_weak_project_bullets_deterministically(
                tex_str,
                refs["base_resume_tex"],
                refs["context_bank"],
            )
            job["deterministic_rewrite_fallbacks"] = fallback_events

        if "EXPERIENCE" in DETERMINISTIC_SECTIONS:
            if deterministic_experience_ready and prebuilt_experience_section:
                tex_str = _replace_experience_section(
                    tex_str, prebuilt_experience_section)
                job["experience_deterministic_ranking"] = prebuilt_experience_diagnostics
                job["experience_deterministic_applied"] = True
            else:
                exp_section_tex, exp_diagnostics = _build_deterministic_experience_section(
                    refs["context_bank"],
                    jd_keywords,
                )
                if exp_section_tex and "\\section{Experience}" in exp_section_tex:
                    tex_str = _replace_experience_section(
                        tex_str, exp_section_tex)
                    job["experience_deterministic_ranking"] = exp_diagnostics
                    job["experience_deterministic_applied"] = True
                else:
                    job["experience_deterministic_applied"] = False
    timings["deterministic_rewrites"] = round(time.perf_counter() - t0, 3)

    # Persist diagnostics for reproducibility/debugging.
    job["project_ranking"] = ranking_diagnostics
    with open(target_dir / "job_details.json", "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

    # Step 3: Compile PDF and handle multi-page retry flow
    t0 = time.perf_counter()
    pdf_res = _compile_latex_to_pdf(
        tex_string=tex_str,
        output_dir=target_dir,
        filename=safe_name,
        sections=sections,
        tailored_content=content,
        template_str=refs["base_resume_tex"]
    )
    timings["pdf_compilation"] = round(time.perf_counter() - t0, 3)

    # Phase 1 validation: warn_only mode. Preserve output and persist warnings.
    t0 = time.perf_counter()
    pre_repair_warnings = _validate_generated_resume_artifacts(
        target_dir, refs["context_bank"]
    )
    timings["validation"] = round(time.perf_counter() - t0, 3)

    validation_warnings = list(pre_repair_warnings)
    repair_classification = _classify_validation_warnings(pre_repair_warnings)
    repair_applied = False

    if pre_repair_warnings:
        repaired_tex = tex_str
        pre_repair_tex = tex_str
        fixable_categories = set(repair_classification["fixable"])
        hard_categories = set(repair_classification["hard"])
        warning_map = _sectioned_bullet_index(pre_repair_tex)
        hard_warning_entries = _hard_warning_entries(
            pre_repair_warnings, warning_map)
        if hard_warning_entries:
            job["validation_warning_locations"] = hard_warning_entries

        if "length" in fixable_categories:
            repaired_tex = _trim_long_bullets_deterministically(repaired_tex)
            repair_applied = True

        if {"ownership", "action_verb"} & fixable_categories:
            repaired_tex, fallback_events = _rewrite_weak_project_bullets_deterministically(
                repaired_tex,
                refs["base_resume_tex"],
                refs["context_bank"],
            )
            job["deterministic_rewrite_fallbacks_after_validation"] = fallback_events
            repair_applied = True

            if settings.get("deterministic_project_bullets", False) and "EXPERIENCE" in DETERMINISTIC_SECTIONS:
                exp_section_tex, exp_diagnostics = _build_deterministic_experience_section(
                    refs["context_bank"],
                    jd_keywords,
                )
                if exp_section_tex and "\\section{Experience}" in exp_section_tex:
                    repaired_tex = _replace_experience_section(
                        repaired_tex, exp_section_tex)
                    job["experience_deterministic_ranking_after_validation"] = exp_diagnostics

        if hard_categories:
            if hard_warning_entries:
                repaired_tex = _fallback_bullets_to_source(
                    repaired_tex,
                    refs["base_resume_tex"],
                    hard_warning_entries,
                )
                repair_applied = True

        if repair_applied:
            repair_compile = _compile_latex_to_pdf(
                tex_string=repaired_tex,
                output_dir=target_dir,
                filename=safe_name,
                sections=sections,
                tailored_content=content,
                template_str=refs["base_resume_tex"],
            )

            if repair_compile.get("status") != "error":
                attempted_post_warnings = _validate_generated_resume_artifacts(
                    target_dir, refs["context_bank"]
                )
                pre_count = len(pre_repair_warnings)
                post_count = len(attempted_post_warnings)

                if post_count >= pre_count:
                    print("[REPAIR] Reverted - repair increased warnings")
                    revert_compile = _compile_latex_to_pdf(
                        tex_string=pre_repair_tex,
                        output_dir=target_dir,
                        filename=safe_name,
                        sections=sections,
                        tailored_content=content,
                        template_str=refs["base_resume_tex"],
                    )
                    if revert_compile.get("status") != "error":
                        pdf_res = revert_compile
                    validation_warnings = list(pre_repair_warnings)
                    repair_applied = False
                else:
                    print(
                        f"[REPAIR] Applied - warnings reduced {pre_count} -> {post_count}")
                    pdf_res = repair_compile
                    validation_warnings = attempted_post_warnings

    job["validation_warnings_pre_repair"] = pre_repair_warnings
    job["validation_warnings_post_repair"] = validation_warnings
    job["validation_warning_classification"] = repair_classification
    job["validation_repair_applied"] = repair_applied

    timings["total_pipeline"] = round(
        time.perf_counter() - t_pipeline_start, 3)

    # Persist timings and warnings into job_details.json
    job["validation_warnings"] = validation_warnings
    job["tailor_timings"] = timings
    with open(target_dir / "job_details.json", "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

    if validation_warnings:
        pdf_res["validation_warnings"] = validation_warnings

    pdf_res["tailor_timings"] = timings
    print(
        f"[TAILOR] Timings for {job.get('company', '?')} - {job.get('title', '?')}:")
    for step, secs in timings.items():
        print(f"  {step}: {secs}s")

    return pdf_res


if __name__ == "__main__":
    # Simple smoke test
    print(safe_filename("Suyesh Jadhav"))
