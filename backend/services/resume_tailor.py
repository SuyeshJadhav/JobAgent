import json
import re
import shutil
import subprocess
import tomllib
import pypdf
from datetime import datetime
from pathlib import Path

from backend.services.llm_client import get_llm_client, get_model_name, get_settings

ROOT_DIR = Path(__file__).parent.parent.parent
REFERENCES_DIR = ROOT_DIR / "references"
OUTPUT_DIR = ROOT_DIR / "outputs" / "applications"

BASE_RESUME = REFERENCES_DIR / "base_resume.tex"
CONTEXT_BANK = REFERENCES_DIR / "context_bank.toml"
CUSTOM_COMMANDS = REFERENCES_DIR / "custom-commands.tex"

def safe_filename(name: str) -> str:
    """Make string safe for filesystem."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()

def load_references() -> dict:
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

def parse_marker_sections(tex_content: str) -> dict:
    pattern = re.compile(
        r"^(?P<indent>\s*)%%\s*BEGIN\s+(?P<name>.+?)\s*%%\s*$"
        r"(?P<body>.*?)"
        r"^(?P=indent)%%\s*END\s+(?P=name)\s*%%\s*$",
        re.MULTILINE | re.DOTALL,
    )
    sections = {}
    for m in pattern.finditer(tex_content):
        name = m.group("name").strip()
        body = m.group("body")

        start_char = m.start()
        end_char = m.end()
        start_line = tex_content[:start_char].count("\n")
        end_line = tex_content[:end_char].count("\n")

        sections[name] = {
            "start": start_line,
            "end": end_line,
            "content": body.strip(),
        }
    return sections

def _get_context_for_section(section_name: str, context_bank: dict) -> str:
    fragments = []
    if section_name.upper().startswith("EXPERIENCE:"):
        company_hint = section_name.split(":", 1)[1].strip().lower()
        for exp in context_bank.get("experience", []):
            if company_hint in exp.get("company", "").lower() or company_hint in exp.get("role", "").lower():
                for key in exp:
                    if key.startswith("project_"):
                        proj = exp[key]
                        if isinstance(proj, list):
                            for p in proj:
                                fragments.append("\n".join(f"  {k}: {v}" for k, v in p.items()))
                        elif isinstance(proj, dict):
                            fragments.append("\n".join(f"  {k}: {v}" for k, v in proj.items()))

    if section_name.upper().startswith("PROJECTS:"):
        project_hint = section_name.split(":", 1)[1].strip().lower()
        for proj in context_bank.get("project", []):
            if project_hint in proj.get("name", "").lower():
                fragments.append("\n".join(f"  {k}: {v}" for k, v in proj.items()))

    return "\n---\n".join(fragments) if fragments else ""

def _get_voice_samples(context_bank: dict) -> str:
    samples = []
    for vs in context_bank.get("voice_samples", []):
        s = vs.get("samples", [])
        if isinstance(s, list):
            samples.extend(s)
    return "\n".join(f"- {s}" for s in samples) if samples else ""

def extract_jd_keywords(jd_text: str) -> dict:
    system = (
        "You are a JD analysis engine. Extract structured keywords. Return ONLY valid JSON with keys: "
        '"required_skills", "action_verbs", "seniority_signals", "domain_focus".'
    )
    client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=get_model_name(),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": jd_text}],
            temperature=0.3
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content)
    except Exception:
        return {"required_skills": [], "action_verbs": [], "seniority_signals": [], "domain_focus": []}

def extract_numbers(text: str) -> set:
    return set(re.findall(r'\b\d+(?:\.\d+)?\b', text))

class HallucinationError(Exception):
    pass

# ─── Post-processing: strip LLM preamble / markdown fences ─────────────

def sanitize_llm_latex(raw: str) -> str:
    """
    Strip markdown code fences, conversational preambles, and <scratchpad>
    tags from LLM output so only clean LaTeX remains.
    """
    # Remove ```latex ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```(?:latex|tex)?\s*", "", raw, flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    # Remove <scratchpad>...</scratchpad> blocks
    text = re.sub(r"<scratchpad>.*?</scratchpad>", "", text, flags=re.DOTALL)
    # Remove conversational preamble lines ("Here are the ...", "Sure! ...")
    text = re.sub(r"^(?:Here|Sure|Below|Note|Okay|The following)[^\\\n]*\n", "", text, flags=re.MULTILINE | re.IGNORECASE)
    # Remove trailing comments like "% Continue with the rest..."
    text = re.sub(r"^%\s*Continue.*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"^%\s*Example of.*$", "", text, flags=re.MULTILINE | re.IGNORECASE)
    return text.strip()


def rewrite_bullets(section_name: str, current_text: str, keywords: dict, context_bank: dict, is_retry: bool = False) -> str:
    context_notes = _get_context_for_section(section_name, context_bank)
    kw_str = json.dumps(keywords, indent=2)

    system = r"""You are a LaTeX resume editor performing SURGICAL keyword integration.

<philosophy>
RULE OF SUBTLETY: You are NOT rewriting bullets from scratch.
You are making MINIMAL, targeted word-swaps to weave JD keywords
into the candidate's EXISTING bullet points. The candidate's
original sentence structure, metrics, and achievements MUST survive.
Think of yourself as a copy-editor, not a ghostwriter.
</philosophy>

<strict_rules>
FORMATTING:
- Preserve every \resumeItem{} wrapper exactly.
- Preserve every \imp{} wrapper exactly.
- Preserve \resumeItemListStart and \resumeItemListEnd if present.
- Output ONLY valid LaTeX. No markdown. No conversational text.
- Each bullet must be ≤ 120 characters of visible text content.

CONTENT INTEGRITY:
- Keep ALL numbers, percentages, and metrics EXACTLY as original.
- Keep ALL tool/framework names EXACTLY as original.
- Do NOT invent projects, tools, skills, or metrics.
- Do NOT add \textbf{}, \section*, headers, or structural LaTeX.
- Do NOT output preambles like "Here are the updated bullets:".
- Do NOT output dummy examples like "Software Engineer, XYZ Corp" etc.

TENSE & GRAMMAR LOCK (CRITICAL):
- You MUST maintain the EXACT tense of the original bullet.
- If the original uses past tense ("Architected", "Built", "Designed"),
  the tailored version MUST remain past tense.
- Do NOT blindly copy present-tense verbs from the job description.
  JD phrases like "Works on", "Supports", "Contributes to",
  "Manages", "Maintains" describe the ROLE, not the candidate's PAST.
  Convert them: "Supports" → "Reinforced", "Works on" → "Built".
- NEVER change a past-tense bullet to present tense.

VERB VARIETY:
- NEVER start two consecutive bullets with the same verb.
- BANNED verbs (never use): Support, Ensure, Deliver, Collaborate,
  Assist, Help, Work on, Contribute, Maintain, Manage, Write.
- PREFER strong past-tense verbs: Built, Engineered, Architected,
  Optimized, Designed, Implemented, Reduced, Accelerated, Shipped,
  Integrated, Developed, Orchestrated, Automated, Deployed, Refactored,
  Spearheaded, Streamlined, Pioneered, Consolidated.

LaTeX ESCAPING (CRITICAL):
- C# → C\#     % → \%     & → \&     _ → \_     $ → \$
- Always escape these characters in generated text.
</strict_rules>

<output_format>
Return ONLY \resumeItem{} lines (with \resumeItemListStart/End if
they were in the input). One per line, no blank lines between them.

Example input:
  \resumeItem{Built a \imp{RAG pipeline} using \imp{LangChain}, reducing query latency from \imp{5min to 30sec}.}
Example output (weaving "retrieval-augmented generation" keyword):
  \resumeItem{Built a \imp{retrieval-augmented generation pipeline} using \imp{LangChain}, reducing query latency from \imp{5min to 30sec}.}
</output_format>"""

    if is_retry:
        system += "\n\nSTRICT WARNING: Your previous attempt hallucinated numbers or violated rules. Use ONLY numbers present in the original text!"

    user_msg = f"""SECTION: {section_name}

JD KEYWORDS TO WEAVE IN:
{kw_str}

REAL CONTEXT (use ONLY these facts — no invention):
{context_notes}

ORIGINAL BULLETS (apply minimal keyword swaps, preserve structure):
{current_text}

Return ONLY the rewritten LaTeX lines now."""

    client = get_llm_client()
    resp = client.chat.completions.create(
        model=get_model_name(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        temperature=0.5
    )
    return sanitize_llm_latex(resp.choices[0].message.content.strip())


def rewrite_skills_section(current_text: str, keywords: dict) -> str:
    """
    Specialized rewriter for the Skills section.
    Only adds/reorders keywords — NEVER converts to bullet points.
    """
    kw_str = json.dumps(keywords, indent=2)

    system = r"""You are a LaTeX resume editor. You are editing ONLY a Skills section.

<strict_rules>
FORMAT:
- The skills section MUST remain a dense, comma-separated list.
- Each line starts with \textbf{Category:} followed by comma-separated skills.
- Lines are separated by \\.
- Do NOT generate \resumeItem{} bullet points for skills.
- Do NOT add conversational text, markdown, or explanations.
- Output ONLY the formatted skill lines, nothing else.

ADDING SKILLS:
- You may ADD relevant ENGINEERING skills from JD keywords.
- Integrate new skills NATURALLY into the existing category lines.
  Example: If "LLMs" or "Generative AI" should be added, place them
  in the existing AI/ML line, not as a new appended phrase.
- You may REORDER skills to front-load JD-relevant ones.
- Do NOT remove existing skills.

BLOCKLIST (NEVER add these to an engineering resume):
- Microsoft Word, Excel, PowerPoint, Outlook, Office 365, Teams
- Google Docs, Google Sheets, Slack, Zoom, Jira, Confluence
- Any basic office/productivity/admin tool
- These are NOT engineering skills. Ignore them even if the JD lists them.

LaTeX ESCAPING:
- C# → C\#     & → \&     % → \%
</strict_rules>

Example output:
\textbf{Languages:} Python, C\#, JavaScript, SQL, Go \\
\textbf{AI/ML:} LangChain, LLMs, PyTorch, HuggingFace Transformers \\
\textbf{Web:} React, FastAPI, Node.js"""

    user_msg = f"""JD KEYWORDS:
{kw_str}

CURRENT SKILLS SECTION:
{current_text}

Return the updated skills lines now."""

    client = get_llm_client()
    resp = client.chat.completions.create(
        model=get_model_name(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        temperature=0.3
    )
    result = sanitize_llm_latex(resp.choices[0].message.content.strip())

    # Safety net: if the LLM still produced \resumeItem, reject and keep original
    if r"\resumeItem" in result:
        print(f"[GUARD] Skills rewriter produced bullet points — rejecting, keeping original.")
        return current_text
    return result


def rewrite_bullets_with_validation(section_name: str, current_text: str, keywords: dict, context_bank: dict) -> str:
    context_notes = _get_context_for_section(section_name, context_bank)
    true_numbers = extract_numbers(context_notes) if context_notes else set()
    true_numbers.update(extract_numbers(current_text))
    
    for attempt in range(2):
        is_retry = attempt > 0
        output = rewrite_bullets(section_name, current_text, keywords, context_bank, is_retry)
        output_numbers = extract_numbers(output)
        
        hallucinated = output_numbers - true_numbers
        if hallucinated:
            print(f"[GUARD] LLM invented number(s) {hallucinated} in section '{section_name}'")
            if attempt == 0:
                continue
            else:
                return current_text
        return output
    return current_text


def trim_bullets(current_text: str) -> str:
    system = r"""You are an expert LaTeX resume editor.
The resume overflows to 2 pages. Your job: shorten each
\resumeItem{} bullet by ~15 characters while keeping
ALL numbers, metrics, and LaTeX macros (\imp{}, \resumeItem{})
perfectly intact.

Rules:
- Output ONLY the shortened \resumeItem{} lines.
- Do NOT output preambles, comments, examples, or markdown.
- Do NOT change any numbers or metric values.
- Do NOT add new content or sections."""

    user_msg = f"""Shorten these bullets:
{current_text}"""

    client = get_llm_client()
    resp = client.chat.completions.create(
        model=get_model_name(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        temperature=0.3
    )
    return sanitize_llm_latex(resp.choices[0].message.content.strip())


def _generate_tailored_content(job_description: str, sections: dict, context_bank: dict) -> dict:
    """
    Routes each section to the appropriate rewriter:
    - HEADER / SUMMARY / EDUCATION → pass through (no changes)
    - SKILLS → dedicated keyword-only rewriter (no bullet conversion)
    - PROJECTS / EXPERIENCE → surgical bullet keyword weaving
    """
    desc = job_description
    if len(desc) > 8000:
        desc = desc[:8000]
    
    keywords = extract_jd_keywords(desc)

    SKIP_SECTIONS = {"HEADER", "SUMMARY", "EDUCATION"}
    rewritten = {}

    for section_name, sec_data in sections.items():
        sec_upper = section_name.upper()

        # Pass-through sections
        if any(skip in sec_upper for skip in SKIP_SECTIONS):
            rewritten[section_name] = sec_data["content"]
            continue

        # Skills → dedicated comma-list rewriter
        if "SKILLS" in sec_upper:
            print(f"Tailoring section (skills mode): {section_name}")
            rewritten[section_name] = rewrite_skills_section(
                sec_data["content"], keywords
            )
            continue

        # Projects / Experience → bullet keyword weaving
        if "PROJECTS" in sec_upper or "EXPERIENCE" in sec_upper:
            print(f"Tailoring section (bullets mode): {section_name}")
            rewritten[section_name] = rewrite_bullets_with_validation(
                section_name, sec_data["content"], keywords, context_bank
            )
            continue

        # Anything else with domain relevance
        if any(k.lower() in sec_upper.lower() for k in keywords.get("domain_focus", [])):
            print(f"Tailoring section (bullets mode): {section_name}")
            rewritten[section_name] = rewrite_bullets_with_validation(
                section_name, sec_data["content"], keywords, context_bank
            )
        else:
            rewritten[section_name] = sec_data["content"]

    return rewritten


def _inject_content_into_tex(template_str: str, tailored_content: dict, sections: dict) -> str:
    """
    Injects tailored content back into the LaTeX template string without altering original sections boundaries.
    """
    lines = template_str.split("\n")
    result_lines = lines.copy()

    for section_name in sorted(tailored_content.keys(), key=lambda s: sections[s]["start"], reverse=True):
        sec = sections[section_name]
        begin_line = sec["start"]
        end_line = sec["end"]
        new_content = tailored_content[section_name]
        result_lines[begin_line + 1:end_line] = [new_content]

    return "\n".join(result_lines)


def _cleanup_aux_files(output_dir: Path, filename: str):
    """
    Cleans up the .aux, .log, and .out files left behind by pdflatex compilation.
    """
    for ext in [".aux", ".log", ".out"]:
        aux_file = output_dir / f"{filename}{ext}"
        if aux_file.exists():
            try:
                aux_file.unlink()
            except OSError:
                pass


def _compile_latex_to_pdf(tex_string: str, output_dir: Path, filename: str,
                          sections: dict = None, tailored_content: dict = None, template_str: str = None) -> dict:
    """
    Handles OS-level subprocess call to compile LaTeX to PDF. Contains logic to trim bullets and compress
    LaTeX spacing if compilation spills onto two pages.
    """
    tex_path = output_dir / "resume.tex"
    pdf_path = output_dir / f"{filename}.pdf"

    tex_path.write_text(tex_string, encoding="utf-8")

    def call_pdflatex():
        return subprocess.run(
            ["pdflatex", f"-jobname={filename}", "-interaction=nonstopmode", "-output-directory", str(output_dir), str(tex_path)],
            capture_output=True, text=True, timeout=60
        )

    def get_page_count():
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

        # Handle > 1 page situations
        if tailored_content and sections and template_str:
            print("Pages > 1. Attempt 1: Trimming bullets...")
            trimmed_rewritten = {}
            for sec, text in tailored_content.items():
                if sec.upper() not in ("SUMMARY", "SKILLS"):
                    trimmed_rewritten[sec] = trim_bullets(text)
                else:
                    trimmed_rewritten[sec] = text

            tailored_tex_trimmed = _inject_content_into_tex(template_str, trimmed_rewritten, sections)
            tex_path.write_text(tailored_tex_trimmed, encoding="utf-8")
            
            call_pdflatex()
            
            if pdf_path.exists() and get_page_count() == 1:
                _cleanup_aux_files(output_dir, filename)
                return {"status": "success", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}
            
            # Carry over the trimmed text to Attempt 2
            tex_string = tailored_tex_trimmed

        print("Pages > 1. Attempt 2: LaTeX compression...")
        compressed_tex = tex_string.replace(r"\setlength{\itemsep}{1pt}", r"\setlength{\itemsep}{0pt}")
        compressed_tex = compressed_tex.replace(r"10pt", r"9.5pt")
        tex_path.write_text(compressed_tex, encoding="utf-8")

        call_pdflatex()

        if pdf_path.exists() and get_page_count() == 1:
            _cleanup_aux_files(output_dir, filename)
            return {"status": "success", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}

        # Final state
        _cleanup_aux_files(output_dir, filename)
        print("Resume is 2 pages. Manual review needed.")
        return {"status": "warning", "warning": "Resume is 2 pages. Manual review needed.", "output_dir": str(output_dir), "pdf_path": str(pdf_path)}

    except FileNotFoundError:
        return {"status": "error", "error": "pdflatex is not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_tailor(job: dict) -> dict:
    """
    Main pipeline to tailor a resume.
    1. Loads contextual data.
    2. Generates tailored content via LLM.
    3. Injects content and safely compiles LaTeX to PDF.
    """
    settings = get_settings()
    candidate_name = settings.get("candidate_name", "Suyesh Jadhav")
    safe_name = safe_filename(candidate_name)

    company = safe_filename(job.get("company", "Unknown"))
    role = safe_filename(job.get("title", "Unknown"))
    date_str = datetime.now().strftime("%Y-%m-%d")

    folder_name = f"{company}-{role}-{date_str}"
    target_dir = OUTPUT_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # Export job details json
    job["tailored_at"] = datetime.now().isoformat()
    with open(target_dir / "job_details.json", "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)

    refs = load_references()
    sections = parse_marker_sections(refs["base_resume_tex"])

    # Step 1: Generate Tailored Content
    content = _generate_tailored_content(
        job_description=job.get("description", ""),
        sections=sections,
        context_bank=refs["context_bank"]
    )

    # Step 2: Inject Content into LaTeX
    tex_str = _inject_content_into_tex(
        template_str=refs["base_resume_tex"],
        tailored_content=content,
        sections=sections
    )

    if CUSTOM_COMMANDS.exists():
        shutil.copy(CUSTOM_COMMANDS, target_dir / "custom-commands.tex")

    # Step 3: Handle compilation, retry flow, and output
    pdf_res = _compile_latex_to_pdf(
        tex_string=tex_str,
        output_dir=target_dir,
        filename=safe_name,
        sections=sections,
        tailored_content=content,
        template_str=refs["base_resume_tex"]
    )

    return pdf_res

if __name__ == "__main__":
    job_mock = {
        "job_id": "test1234",
        "company": "Test Company",
        "title": "Data Scientist",
        "description": "We need Python, SQL, and Machine Learning expertise.",
        "score": 9,
        "reason": "Good match",
        "apply_link": "https://example.com"
    }
    
    # We will test simply if the files parse ok!
    print(safe_filename("Suyesh Jadhav"))
