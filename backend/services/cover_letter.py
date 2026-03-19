import tomllib
import subprocess
import re
from pathlib import Path
from urllib.parse import urlparse

from backend.services.llm_client import get_llm_client, get_model_name
from backend.services.db_tracker import _get_readable_job_dir
from backend.utils.latex_parser import cleanup_latex_aux_files, escape_latex_text
from backend.utils.reference_loader import load_references

ROOT_DIR = Path(__file__).parent.parent.parent
REFERENCES_DIR = ROOT_DIR / "references"
OUTPUT_DIR = ROOT_DIR / "outputs" / "applications"

CANDIDATE_PROFILE = REFERENCES_DIR / "candidate_profile.md"
COVER_LETTER_TONE = REFERENCES_DIR / "cover_letter_template.md"
COVER_LETTER_TEX_TEMPLATE = REFERENCES_DIR / "cover_letter.tex"
CONTEXT_BANK = REFERENCES_DIR / "context_bank.toml"

_HEADER_LINE_RE = re.compile(
    r"^(?:subject\s*:|re\s*:|date\s*:|to\s*:|from\s*:|hiring team|{{company}}|{{role}})",
    flags=re.IGNORECASE,
)
_CONTACT_LINE_RE = re.compile(
    r"(?:@|linkedin\.com|github\.com|\+?\d[\d\-\s\(\)]{6,}|raleigh,\s*nc)",
    flags=re.IGNORECASE,
)
_SALUTATION_RE = re.compile(r"^(?:dear|hello|hi)\b", flags=re.IGNORECASE)
_CLOSING_RE = re.compile(
    r"^(?:best|best regards|regards|sincerely|thank you|thanks|warm regards)\b",
    flags=re.IGNORECASE,
)
_NAME_ONLY_RE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}$")
_DATE_LINE_RE = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4}$",
    flags=re.IGNORECASE,
)


def _build_context_summary(context_bank: dict) -> str:
    """
    Build a concise text summary of experience + projects from context_bank
    so the LLM has real details to draw from.
    """
    parts = []

    for exp in context_bank.get("experience", []):
        company = exp.get("company", "Unknown")
        role = exp.get("role", "")
        parts.append(f"## {role} @ {company}")
        for key in sorted(exp.keys()):
            if key.startswith("project_"):
                proj = exp[key]
                if isinstance(proj, list):
                    for p in proj:
                        lines = [f"  {k}: {v}" for k, v in p.items()]
                        parts.append("\n".join(lines))
                elif isinstance(proj, dict):
                    lines = [f"  {k}: {v}" for k, v in proj.items()]
                    parts.append("\n".join(lines))

    for proj in context_bank.get("project", []):
        name = proj.get("name", "Unnamed")
        parts.append(f"## Project: {name}")
        lines = [f"  {k}: {v}" for k, v in proj.items() if k != "name"]
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _extract_valid_projects_and_tools(context_bank: dict) -> tuple[set[str], set[str]]:
    """Extract all valid project names and technologies from context_bank."""
    valid_projects = set()
    valid_tools = set()

    # Extract project names from experience section
    for exp in context_bank.get("experience", []):
        for key in exp.keys():
            if key.startswith("project_"):
                proj = exp[key]
                if isinstance(proj, dict):
                    for value in proj.values():
                        if isinstance(value, str):
                            # Extract tool names
                            for tool in re.findall(r"\b([A-Za-z0-9.+\-]+(?:\s+[A-Za-z0-9.+\-]+)*)\b", value):
                                if len(tool) > 2:
                                    valid_tools.add(tool.lower())

    # Extract project names and tools from project section
    for proj in context_bank.get("project", []):
        name = proj.get("name", "").strip()
        if name:
            valid_projects.add(name.lower())

        # Extract tools from tools_used/stack fields across list+string schemas.
        tools_used = proj.get("tools_used", "") or proj.get("stack", "")
        if isinstance(tools_used, list):
            tool_items = [str(item).strip()
                          for item in tools_used if str(item).strip()]
        elif isinstance(tools_used, str):
            tool_items = [item.strip() for item in re.split(
                r",|\+", tools_used) if item.strip()]
        else:
            tool_items = [str(tools_used).strip()] if tools_used else []

        for tool in tool_items:
            valid_tools.add(tool.lower())

    return valid_projects, valid_tools


def _strip_fictional_projects(text: str, valid_projects: set[str], valid_tools: set[str]) -> str:
    """
    Remove or replace references to projects/tools not in the candidate's actual portfolio.
    Targets patterns like "developing a X simulator", "building a Y system", etc.
    """
    if not text or (not valid_projects and not valid_tools):
        return text

    # Pattern 1: "developing/building/creating a [PROJECT] [simulator/system/engine/platform/game]"
    pattern_dev = r"\b(?:developing|building|creating|working on|wrote|implemented|designed)\s+(?:a|an|the)?\s+(?:automated\s+)?(\w+(?:\s+\w+)*?)\s+(?:simulator|system|platform|application|tool|engine|framework|game|bot|app|website|platform|dashboard)\b"

    def validate_project_or_tool(project_name: str) -> bool:
        """Check if project_name is in the candidate's portfolio."""
        name_lower = project_name.lower()
        # Check against valid projects
        for valid_proj in valid_projects:
            if name_lower in valid_proj or valid_proj in name_lower:
                return True
        # Check against valid tools (looser match - tools are often single words)
        for valid_tool in valid_tools:
            if name_lower == valid_tool or name_lower in valid_tool:
                return True
        return False

    def replace_dev(match):
        project_name = match.group(1).strip()
        if not validate_project_or_tool(project_name):
            return ""  # Remove entirely
        return match.group(0)  # Keep it

    result = re.sub(pattern_dev, replace_dev, text, flags=re.IGNORECASE)

    # Pattern 2: "my [recent] project [involving/on] [PROJECT]" + outcome clause
    pattern_project = r"\b(?:my\s+(?:recent\s+)?project\s+(?:involving|on)\s+(?:a|an|the)?\s+(\w+(?:\s+\w+)*?)[\s,])"

    def replace_project(match):
        project_name = match.group(1).strip()
        if not validate_project_or_tool(project_name):
            # Find and remove the whole sentence containing this pattern
            return ""
        return match.group(0)

    result = re.sub(pattern_project, replace_project,
                    result, flags=re.IGNORECASE)

    # Pattern 3: Remove entire sentences with fictional games/projects
    # e.g., "My recent project involving a Mario game engine aligned with requirements."
    sentences = result.split(". ")
    filtered_sentences = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Check if sentence contains obvious fictional game/project keywords
        fictional_keywords = ["pokémon", "pokemon", "mario", "zelda",
                              "minecraft", "roblox", "fortnite", "valorant", "league of legends"]
        contains_fictional = any(kw in sentence.lower()
                                 for kw in fictional_keywords)

        if contains_fictional:
            # Skip this sentence
            continue

        filtered_sentences.append(sentence)

    result = ". ".join(filtered_sentences)
    if result and not result.endswith("."):
        result += "."

    # Clean up multiple spaces and fix spacing
    result = re.sub(r" {2,}", " ", result)
    result = re.sub(r"\.\s*\.", ".", result)
    return result.strip()


def _extract_company_from_apply_link(apply_link: str) -> str:
    """Best-effort company extraction from job URL when DB fields are malformed."""
    if not apply_link:
        return ""

    try:
        parsed = urlparse(apply_link)
        netloc = parsed.netloc.lower()
        parts = [p for p in netloc.split(".") if p and p != "www"]
        if len(parts) >= 2:
            candidate = parts[-2]
            if candidate not in {"jobs", "careers", "boards", "apply", "myworkdayjobs"}:
                return candidate.replace("-", " ").replace("_", " ").title()

        path_tokens = [p for p in parsed.path.split("/") if p]
        if path_tokens:
            return path_tokens[0].replace("-", " ").replace("_", " ").title()
    except Exception:
        return ""

    return ""


def _extract_role_from_description(desc: str) -> str:
    """Find a likely job title line from scraped JD text."""
    if not desc:
        return ""

    role_kw = re.compile(
        r"\b(intern|engineer|developer|scientist|analyst|architect|manager|specialist|associate|technician)\b",
        flags=re.IGNORECASE,
    )
    noise = {
        "skip to content",
        "general information",
        "description and requirements",
        "key responsibilities",
        "required qualifications",
    }

    for raw_line in desc.splitlines()[:80]:
        line = re.sub(r"\s+", " ", raw_line).strip(" -:\t")
        if not line:
            continue
        lowered = line.lower()
        if lowered in noise:
            continue
        if "http" in lowered or lowered.startswith("req #"):
            continue
        if line.isupper() and len(line.split()) <= 3:
            continue
        if len(line) < 6 or len(line) > 110:
            continue
        if role_kw.search(line):
            return line

    return ""


def _normalize_company_and_role(job: dict) -> tuple[str, str]:
    """Repair malformed company/title fields from tracker payloads."""
    raw_company = str(job.get("company", "") or "").strip()
    raw_role = str(job.get("title", "") or "").strip()
    desc = str(job.get("description", "") or "")
    apply_link = str(job.get("apply_link", "") or "")

    inferred_company = _extract_company_from_apply_link(apply_link)
    inferred_role = _extract_role_from_description(desc)

    def _is_bad_company(value: str) -> bool:
        v = value.strip().lower()
        return (not v) or v in {"unknown", "n/a"} or bool(re.fullmatch(r"\d{3,}", v))

    def _is_bad_role(value: str) -> bool:
        v = value.strip().lower()
        if not v or v in {"unknown", "n/a"}:
            return True
        if bool(re.fullmatch(r"wd\d+|\d{3,}", v, flags=re.IGNORECASE)):
            return True
        return False

    company = raw_company
    role = raw_role

    # Common corruption pattern: company contains req id and title contains company name.
    if _is_bad_company(raw_company) and inferred_company and raw_role.lower() == inferred_company.lower():
        company = inferred_company
        if inferred_role:
            role = inferred_role

    if _is_bad_company(company) and inferred_company:
        company = inferred_company

    if (_is_bad_role(role) or (company and role.lower() == company.lower())) and inferred_role:
        role = inferred_role

    if not company:
        company = "Unknown"
    if not role:
        role = "Unknown"
    return company, role


def generate_cover_letter_content(
    jd_text: str,
    company: str,
    role: str,
    candidate_profile: str,
    cover_letter_tone: str,
    context_summary: str,
) -> str:
    system = (
        "Write a cover letter for this candidate applying to this job.\n\n"
        f"CANDIDATE:\n{candidate_profile}\n\n"
        f"REAL PROJECT DETAILS (use these — never invent):\n{context_summary}\n\n"
        f"JD:\n{jd_text}\n\n"
        f"COMPANY: {company}\n"
        f"ROLE: {role}\n\n"
        f"TONE GUIDE:\n{cover_letter_tone}\n\n"
        "Rules — follow ALL of these:\n"
        "- Max 250 words total\n"
        "- Exactly 3 paragraphs:\n"
        "    Para 1 — Hook: reference something specific from the JD or company\n"
        "    Para 1 — MUST explicitly include the exact company name at least once\n"
        "    Para 2 — Value: pick the 2 most relevant experiences from the context above, "
        "use JD language\n"
        "    Para 3 — Close: one confident sentence CTA, no begging\n"
        "- Sound human, not corporate\n"
        '- No generic openers like "I am excited to apply"\n'
        "- Do NOT repeat resume bullets word for word — complement them\n"
        "- Reference something specific from the JD\n"
        "- Show tools in action within sentences, do not list them\n"
        '- No "passionate", "driven", or "hardworking" — show, don\'t tell\n\n'
        "ANTI-HALLUCINATION (CRITICAL - BREAKING THIS IS A FATAL ERROR):\n"
        f"- NEVER claim the candidate previously worked at or built anything at {company}\n"
        f"- ONLY reference experiences from the REAL PROJECT DETAILS section\n"
        "- If the JD mentions 'BOM data analysis' or similar, do NOT say 'my recent project involving BOM data analysis at [Company]'\n"
        "- Distinguish between: [JD language about the role] vs [candidate's real projects from REAL PROJECT DETAILS]\n"
        "- Use phrases like 'would enable me to contribute' and 'aligns with' rather than 'at [Company]' or 'my work on [Company] systems'\n\n"
        "Output contract (strict):\n"
        "- Return ONLY the letter body text content\n"
        "- Do NOT include candidate name/contact details/date\n"
        "- Do NOT include company/role header lines\n"
        "- Do NOT include greeting line (e.g., Dear Hiring Manager)\n"
        "- Do NOT include closing/signature lines\n"
        "- Do NOT use markdown, bullets, numbering, or code fences\n"
        "- No placeholders like {{COMPANY}} or {{ROLE}}"
    )

    print(f"[COVER] Generating for: {company}")
    client = get_llm_client()
    try:
        resp = client.chat.completions.create(
            model=get_model_name(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": "Generate the cover letter now."}
            ],
            temperature=0.7
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating cover letter: {e}")
        return ""


def _is_noise_line(line: str) -> bool:
    if not line:
        return False
    lowered = line.lower()
    if _HEADER_LINE_RE.match(line):
        return True
    if _CONTACT_LINE_RE.search(line):
        return True
    if _DATE_LINE_RE.match(line):
        return True
    if lowered in {"hiring manager", "hiring team"}:
        return True
    return False


def _truncate_paragraphs(paragraphs: list[str], max_words: int) -> list[str]:
    kept: list[str] = []
    remaining = max_words
    for p in paragraphs:
        if remaining <= 0:
            break
        words = p.split()
        if not words:
            continue
        if len(words) <= remaining:
            kept.append(" ".join(words))
            remaining -= len(words)
        else:
            kept.append(" ".join(words[:remaining]).rstrip(",;:"))
            remaining = 0
    return [p for p in kept if p.strip()]


def _strip_false_company_claims(text: str, company_name: str) -> str:
    """Remove false attributions like 'at [Company]' or 'my work at [Company]'."""
    if not company_name:
        return text

    company_lower = company_name.lower()
    patterns = [
        rf"\b(?:my|I)(?:\s+[a-z]+)*\s+(?:project|work|experience|tools?)\s+(?:on|involving|with|in).*?\bat\s+{re.escape(company_lower)}\b",
        rf"\bat\s+{re.escape(company_lower)}\b(?:\s*,)?(?:\s+(?:where|that|which)\s+I\s+[\'d]\s+)*",
        rf"\bduring\s+my\s+(?:time|work)\s+at\s+{re.escape(company_lower)}\b",
    ]

    result = text
    for pattern in patterns:
        result = re.sub(pattern, "", result,
                        flags=re.IGNORECASE | re.MULTILINE)

    # Clean up multiple spaces on same line, but preserve paragraph breaks (newlines)
    result = re.sub(r" {2,}", " ", result)
    return result


def clean_llm_cover_letter(raw: str, max_words: int = 250, company_name: str = "", context_bank: dict = None) -> str:
    """Normalize LLM output to plain body paragraphs suitable for template injection."""
    if not raw:
        return ""

    text = raw.replace("\r\n", "\n").strip()
    text = re.sub(r"^```(?:[a-zA-Z]+)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"<think>.*?</think>", "", text,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<\|.*?\|>", "", text)
    text = re.sub(r"\[(?:\s*your[^\]]*|\s*company name\s*|\s*role title\s*|\s*hiring manager name\s*)\]",
                  "", text, flags=re.IGNORECASE)

    text = _strip_false_company_claims(text, company_name)

    # Strip fictional projects if context_bank is provided
    if context_bank:
        valid_projects, valid_tools = _extract_valid_projects_and_tools(
            context_bank)
        text = _strip_fictional_projects(text, valid_projects, valid_tools)

    cleaned_lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue

        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)

        lowered = line.lower()
        if lowered.startswith(("certainly", "of course", "sure", "here is", "here's")):
            continue
        if "tailored cover letter" in lowered:
            continue

        if _is_noise_line(line):
            continue
        if _SALUTATION_RE.match(line):
            continue
        if _CLOSING_RE.match(line):
            continue
        if _NAME_ONLY_RE.match(line):
            continue

        cleaned_lines.append(line)

    # Remove repeated blank lines.
    normalized_lines: list[str] = []
    prev_blank = False
    for line in cleaned_lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        normalized_lines.append(line)
        prev_blank = is_blank

    paragraphs = [p.strip() for p in re.split(
        r"\n\s*\n+", "\n".join(normalized_lines).strip()) if p.strip()]
    if not paragraphs:
        return ""

    # Template already contains greeting + signature.
    if paragraphs and _SALUTATION_RE.match(paragraphs[0]):
        paragraphs = paragraphs[1:]
    while paragraphs and (_CLOSING_RE.match(paragraphs[-1]) or _NAME_ONLY_RE.match(paragraphs[-1])):
        paragraphs = paragraphs[:-1]

    if not paragraphs:
        return ""

    if len(paragraphs) > 3:
        paragraphs = paragraphs[:2] + [" ".join(paragraphs[2:])]

    # Ensure the opening paragraph contains the exact company token used in the job record.
    if company_name and paragraphs:
        if company_name.lower() not in paragraphs[0].lower():
            paragraphs[0] = f"At {company_name}, {paragraphs[0]}"

    paragraphs = _truncate_paragraphs(paragraphs, max_words=max_words)
    return "\n\n".join(paragraphs).strip()


def _compile_cover_letter_to_pdf(tex_content: str, output_dir: Path, filename: str) -> dict:
    """
    Compiles LaTeX to PDF using pdflatex.
    """
    tex_path = output_dir / "cover_letter.tex"
    pdf_path = output_dir / f"{filename}.pdf"

    tex_path.write_text(tex_content, encoding="utf-8")

    try:
        pid = subprocess.run(
            ["pdflatex", f"-jobname={filename}", "-interaction=nonstopmode",
             "-output-directory", str(output_dir), str(tex_path)],
            capture_output=True, text=True, timeout=30
        )
        if not pdf_path.exists():
            return {"status": "error", "error": f"PDF compilation failed: {pid.stdout[-500:]}"}

        cleanup_latex_aux_files(output_dir, filename)
        return {"status": "success", "pdf_path": str(pdf_path)}
    except FileNotFoundError:
        return {"status": "error", "error": "pdflatex is not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_cover_letter(
    job: dict,
    references_override: Path = None,
    candidate_name: str = None,
    groq_api_key: str = None
) -> dict:
    """
    Main pipeline to generate a cover letter.
    Writes output into the same target directory as resume_tailor:
    outputs/applications/{Company}-{Role}-{YYYY-MM-DD}/cover_letter.pdf

    Args:
        job (dict): Job metadata.
        references_override (Path, optional): Load reference files from this directory.
        candidate_name (str, optional): Override candidate name (not used in cover letter, but kept for API consistency).
        groq_api_key (str, optional): Groq API key override.
    """
    target_dir = _get_readable_job_dir(job)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Load references from override dir or default
    if references_override:
        from backend.services.resume_tailor import _load_references_from_dir
        refs = _load_references_from_dir(references_override)
    else:
        refs = load_references()
    context_summary = _build_context_summary(refs["context_bank"])

    desc = job.get("description", "")
    if len(desc) > 8000:
        desc = desc[:8000]

    company_name, job_title = _normalize_company_and_role(job)

    letter_text = generate_cover_letter_content(
        jd_text=desc,
        company=company_name,
        role=job_title,
        candidate_profile=refs["candidate_profile"],
        cover_letter_tone=refs["cover_letter_tone"],
        context_summary=context_summary
    )

    letter_text = clean_llm_cover_letter(
        letter_text, max_words=250, company_name=company_name, context_bank=refs["context_bank"])
    if not letter_text:
        return {"status": "error", "error": "Cover letter generation failed."}

    # Persist markdown version for inspection/debug and UI consumption.
    md_path = target_dir / "cover_letter.md"
    md_path.write_text(letter_text, encoding="utf-8")

    # If no LaTeX template exists, fall back to .md
    if not refs["cover_letter_tex_template"]:
        return {"status": "success", "output_dir": str(target_dir), "cover_letter_path": str(md_path)}

    # Prepare LaTeX content
    tex_content = refs["cover_letter_tex_template"]
    tex_content = tex_content.replace(
        "{{COMPANY}}", escape_latex_text(company_name))
    tex_content = tex_content.replace(
        "{{ROLE}}", escape_latex_text(job_title))
    tex_content = tex_content.replace(
        "{{CONTENT}}", escape_latex_text(letter_text))

    # Optional: Basic escaping for letter_text if it contains LaTeX special chars
    # However, LLM is instructed to return plain text. If we escape too much, it might break formatting.
    # We should at least escape common ones.
    # But wait, generated cover letter usually doesn't have math symbols.
    # For now, let's just use it as is or do a light pass.
    # Actually, resume_tailor uses _sanitize_tex_string.

    res = _compile_cover_letter_to_pdf(tex_content, target_dir, "cover letter")
    if res["status"] == "success":
        return {
            "status": "success",
            "output_dir": str(target_dir),
            "cover_letter_path": str(md_path),
            "cover_letter_pdf_path": res["pdf_path"],
        }
    else:
        # Markdown is already persisted above.
        return {"status": "warning", "warning": res["error"], "cover_letter_path": str(md_path)}


if __name__ == "__main__":
    test_job = {
        "company": "Test Company",
        "title": "Data Scientist",
        "description": "We need someone with Python, SQL, and Machine Learning expertise.",
    }
    # It attempts a dry run to generate output files
    print(run_cover_letter(test_job))
