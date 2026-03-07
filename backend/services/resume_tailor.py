import json
import shutil
import subprocess
import pypdf
from datetime import datetime
from pathlib import Path

from backend.services.llm_client import get_settings
from backend.utils.latex_parser import (
    safe_filename,
    parse_marker_sections,
    inject_content_into_tex,
    cleanup_latex_aux_files
)
from backend.services.resume_generators import (
    generate_tailored_content,
    trim_bullets
)

ROOT_DIR = Path(__file__).parent.parent.parent
REFERENCES_DIR = ROOT_DIR / "references"
OUTPUT_DIR = ROOT_DIR / "outputs" / "applications"

BASE_RESUME = REFERENCES_DIR / "main.tex"
CONTEXT_BANK = REFERENCES_DIR / "context_bank.toml"

def load_references() -> dict:
    """
    Loads core reference files (Base Resume LaTeX and Context Bank TOML).
    
    Returns:
        dict: Contains 'base_resume_tex' string and 'context_bank' dictionary.
    
    Raises:
        FileNotFoundError: If the base resume file is missing.
    """
    import tomllib # Ensure tomllib is available if not globally imported
    refs = {}
    if BASE_RESUME.exists():
        refs["base_resume_tex"] = BASE_RESUME.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(f"Missing {BASE_RESUME}")
        
    if CONTEXT_BANK.exists():
        with open(CONTEXT_BANK, "rb") as f:
            refs["context_bank"] = tomllib.load(f)
    else:
        refs["context_bank"] = {}
        
    return refs

def _cleanup_aux_files(output_dir: Path, filename: str):
    """Internal helper to remove LaTeX auxiliary files after compilation."""
    cleanup_latex_aux_files(output_dir, filename)

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

    tex_path.write_text(tex_string, encoding="utf-8")

    def call_pdflatex():
        """Helper to invoke the pdflatex subprocess."""
        return subprocess.run(
            ["pdflatex", f"-jobname={filename}", "-interaction=nonstopmode", "-output-directory", str(output_dir), str(tex_path)],
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

            tailored_tex_trimmed = inject_content_into_tex(template_str, trimmed_rewritten, sections)
            tex_path.write_text(tailored_tex_trimmed, encoding="utf-8")
            call_pdflatex()
            
            if pdf_path.exists() and get_page_count() == 1:
                _cleanup_aux_files(output_dir, filename)
                return {"status": "success", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}
            
            tex_string = tailored_tex_trimmed # Carry trimmed result to next attempt

        # --- Recovery Pass 2: Layout Compression ---
        print("[TAILOR] Pages > 1. Attempt 2: LaTeX compression...")
        compressed_tex = tex_string.replace(r"\setlength{\itemsep}{1pt}", r"\setlength{\itemsep}{0pt}")
        compressed_tex = compressed_tex.replace(r"10pt", r"9.5pt")
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

    # Step 1: Generate Tailored Content via LLM service
    content = generate_tailored_content(
        job_description=job.get("description", ""),
        sections=sections,
        context_bank=refs["context_bank"],
        strategy=job.get("strategy", "full_rewrite")
    )

    # Step 2: Inject Content into LaTeX template
    tex_str = inject_content_into_tex(
        template_str=refs["base_resume_tex"],
        tailored_content=content,
        sections=sections
    )

    # Step 3: Compile PDF and handle multi-page retry flow
    pdf_res = _compile_latex_to_pdf(
        tex_string=tex_str,
        output_dir=target_dir,
        filename=safe_name,
        sections=sections,
        tailored_content=content,
        template_str=refs["base_resume_tex"]
    )

    # Step 4: Final cleanup of secondary tracking artifacts
    if job_id:
        old_dir = OUTPUT_DIR / str(job_id)
        if old_dir.exists() and old_dir.is_dir() and old_dir != target_dir:
            try:
                shutil.rmtree(old_dir)
            except Exception as e:
                print(f"[WARN] Failed to clean up initial fetch dir {old_dir}: {e}")

    return pdf_res

if __name__ == "__main__":
    # Simple smoke test
    print(safe_filename("Suyesh Jadhav"))
