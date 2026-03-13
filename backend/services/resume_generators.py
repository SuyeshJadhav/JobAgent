import json
import re
from pathlib import Path
from backend.services.llm_client import get_llm_client, get_model_name

def sanitize_llm_latex(raw: str) -> str:
    """
    Strip markdown code fences, conversational preambles, and <scratchpad>
    tags from LLM output so only clean LaTeX remains.
    
    Args:
        raw (str): Raw string from LLM response.
        
    Returns:
        str: Cleaned LaTeX string.
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

def extract_numbers(text: str) -> set:
    """
    Extract all numbers (integers and floats) from text for hallucination checks.
    
    Args:
        text (str): Input text.
        
    Returns:
        set: A set of number strings found in the text.
    """
    return set(re.findall(r'\b\d+(?:\.\d+)?\b', text))

def extract_jd_keywords(jd_text: str) -> dict:
    """
    Uses LLM to extract structured context and keywords from the job description.
    
    Args:
        jd_text (str): The raw text of the job description.
        
    Returns:
        dict: A dictionary containing lists of skills, action verbs, etc.
    """
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

def get_context_for_section(section_name: str, context_bank: dict) -> str:
    """
    Extracts ground-truth context from the context_bank to help the LLM provide accurate facts.
    Matches section names (e.g., 'EXPERIENCE: Google') to relevant entries in the bank.
    
    Args:
        section_name (str): The name of the LaTeX section being tailored.
        context_bank (dict): The master data from context_bank.toml.
        
    Returns:
        str: A concatenated string of relevant facts for that section.
    """
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

def rewrite_bullets(section_name: str, current_text: str, keywords: dict, context_bank: dict, is_retry: bool = False) -> str:
    """
    Internal LLM call to perform surgical keyword integration into bullet points.
    
    Args:
        section_name (str): Name of the section being edited.
        current_text (str): Original LaTeX bullets (\bitem{...}).
        keywords (dict): Derived JD keywords.
        context_bank (dict): Reference data for fact verification.
        is_retry (bool): If True, adds extra warnings to prevent hallucination.
        
    Returns:
        str: Rewritten LaTeX bullets.
    """
    context_notes = get_context_for_section(section_name, context_bank)
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
- Preserve every \bitem{} wrapper exactly.
- Output ONLY valid LaTeX. No markdown. No conversational text.
- Each bullet must be ≤ 140 characters of visible text content.

CONTENT INTEGRITY & ANTI-HALLUCINATION (BREAKING THIS IS A FATAL ERROR):
- Keep ALL numbers, percentages, and metrics EXACTLY as original.
- Keep ALL tool/framework names EXACTLY as original.
- Do NOT invent projects, tools, skills, or metrics.
- Do NOT add \textbf{}, \section*, headers, or structural LaTeX.
- Do NOT output preambles like "Here are the updated bullets:".
- Do NOT output dummy examples like "Software Engineer, XYZ Corp" etc.
- Do NOT reinvent and add random tools to the EXPERIENCE section bullets.
- NEVER add your own parenthetical commentary or conceptual tags to the end of bullets (e.g., NEVER add "(performance analysis)" or "(performance improvement)").
- NEVER copy subjective modifiers or parenthetical notes from the JD (e.g., if JD says "Python (primarily within JupyterHub)", use ONLY "Python" if it's in the actual context).

TENSE & GRAMMAR LOCK (CRITICAL):
- You MUST maintain the EXACT tense of the original bullet.
- If the original uses past tense ("Architected", "Built", "Designed"),
  the tailored version MUST remain past tense.
- Do NOT blindly copy present-tense verbs from the job description.

LaTeX ESCAPING (CRITICAL):
- C# → C\#     % → \%     & → \&     _ → \_     $ → \$
- Always escape these characters in generated text.

HIGHLIGHTING:
- Use \textbf{...} for specific keyword emphasis inside a \bitem.
- NEVER use the old \imp macro.
</strict_rules>

<output_format>
Return ONLY \bitem{} lines. One per line, no blank lines between them.
</output_format>"""

    if is_retry:
        system += "\n\nSTRICT WARNING: Your previous attempt hallucinated numbers or violated rules. Use ONLY numbers present in the original text!"

    user_msg = f"""SECTION: {section_name}

JD KEYWORDS TO WEAVE IN (IF APPLICABLE):
{kw_str}

REAL CONTEXT (use ONLY these facts — no invention):
{context_notes}
FATAL RULE: If you cannot weave a keyword without inventing a programming language (like Angular, Java, C#, etc.) not explicitly listed in the REAL CONTEXT above, you MUST ignore the keyword entirely.

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

def rewrite_skills_section(current_text: str, keywords: dict, context_bank: dict) -> str:
    """
    Specialized rewriter for the Skills section (comma-separated lists).
    Loads the master skills.md to ensure all claims are backed by the candidate's core profile.
    
    Args:
        current_text (str): Current LaTeX skills block.
        keywords (dict): Derived JD keywords.
        context_bank (dict): Reference data.
        
    Returns:
        str: Updated LaTeX skills header lines.
    """
    kw_str = json.dumps(keywords, indent=2)
    
    # Load candidate's master skills file
    skills_md = ""
    skills_path = Path(__file__).parent.parent.parent / "profile" / "skills.md"
    if skills_path.exists():
        with open(skills_path, "r", encoding="utf-8") as f:
            skills_md = f.read()

    system = r"""You are a LaTeX resume editor. You are editing ONLY a Skills section.

<strict_rules>
FORMAT:
- The skills section MUST remain a dense, comma-separated list.
- Each line starts with \textbf{Category:} followed by comma-separated skills.
- Lines are separated by \\.
- Output ONLY the formatted skill lines, nothing else.

STRICT EXTRACTION AND PRUNING (CRITICAL):
- You MUST reduce the skills layout to a STRICT MAXIMUM of 4 or 5 category lines.
- Evaluate the MASTER SKILLS BANK and pick EXACTLY 4 or 5 categories that are most relevant to the JD Keywords.
- You must use the EXACT category names from the MASTER SKILLS BANK (but formatted nicely, e.g., \textbf{Backend Frameworks:}).
- You must use ONLY the EXACT skills listed within those categories in the MASTER SKILLS BANK.
- DO NOT invent any new skills, even if the JD asks for them. If it is not in the MASTER SKILLS BANK, the candidate does not know it.
- DO NOT invent any new categories.
- You may REORDER the skills within a category to prioritize those mentioned in the JD.
- Delete all other categories to save space.

BLOCKLIST (NEVER add these to an engineering resume):
- Microsoft Word, Excel, Slack, Zoom, Jira, Confluence, etc.
- NEVER copy subjective modifiers or parenthetical notes from the JD (e.g., if JD says "Python (primarily Jupyter)", use ONLY "Python").

LaTeX ESCAPING:
- C# → C\#     & → \&     % → \%
</strict_rules>"""

    user_msg = f"""JD KEYWORDS:
{kw_str}

MASTER SKILLS BANK (Use this as unquestionable truth for candidate capability):
{skills_md}

CURRENT SKILLS SECTION:
{current_text}

Return the updated skills lines now."""

    client = get_llm_client()
    resp = client.chat.completions.create(
        model=get_model_name(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
        temperature=0.4
    )
    result = sanitize_llm_latex(resp.choices[0].message.content.strip())

    # Safety net: if the LLM still produced \bitem, reject and keep original
    if r"\bitem" in result:
        print(f"[GUARD] Skills rewriter produced bullet points — rejecting, keeping original.")
        return current_text
    return result

def rewrite_bullets_with_validation(section_name: str, current_text: str, keywords: dict, context_bank: dict) -> str:
    """
    Wrapper for rewrite_bullets that adds a numeric validation layer.
    Ensures the LLM doesn't hallucinate metrics (e.g. changing '50%' to '90%').
    
    Args:
        section_name (str): Section name.
        current_text (str): Original text.
        keywords (dict): JD keywords.
        context_bank (dict): Reference data.
        
    Returns:
        str: Validated rewritten LaTeX.
    """
    context_notes = get_context_for_section(section_name, context_bank)
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
                return current_text # Fallback to original on double-fail
        return output
    return current_text

def trim_bullets(current_text: str) -> str:
    """
    Shortens bullets iteratively if the resume spills onto a second page.
    Focuses on character count reduction without losing core impact.
    
    Args:
        current_text (str): The LaTeX bullets.
        
    Returns:
        str: Shortened LaTeX bullets.
    """
    system = r"""You are an expert LaTeX resume editor.
The resume overflows to 2 pages. Your job: shorten each
\bitem{} bullet by ~15 characters while keeping
ALL numbers, metrics, and LaTeX macros (\textbf{}, \bitem{})
perfect intact.

Rules:
- Output ONLY the shortened \bitem{} lines.
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

def generate_tailored_content(job_description: str, sections: dict, context_bank: dict, strategy: str = "full_rewrite") -> dict:
    """
    The orchestrator for section-by-section content generation.
    Decides based on section name which rewriter (Skills vs Bullets) to use.
    
    Args:
        job_description (str): Full JD text.
        sections (dict): Parsed LaTeX sections from the template.
        context_bank (dict): Master profile data.
        strategy (str): 'full_rewrite' or 'skills_only'.
        
    Returns:
        dict: Mapping of section names to their tailored content strings.
    """
    desc = job_description
    if len(desc) > 8000:
        desc = desc[:8000] # Truncate massive JDs for token efficiency
    
    keywords = extract_jd_keywords(desc)

    SKIP_SECTIONS = {"HEADER", "SUMMARY", "EDUCATION", "PROFESSIONAL SUMMARY"}
    rewritten = {}

    for section_name, sec_data in sections.items():
        sec_upper = section_name.upper()

        # Pass-through sections (Headings, Intro, Education)
        if any(skip in sec_upper for skip in SKIP_SECTIONS):
            rewritten[section_name] = sec_data["content"]
            continue

        # Skills → dedicated comma-list rewriter
        if "SKILLS" in sec_upper:
            print(f"[GEN] Tailoring section (skills mode): {section_name}")
            rewritten[section_name] = rewrite_skills_section(
                sec_data["content"], keywords, context_bank
            )
            continue

        # Projects / Experience → bullet keyword weaving
        if "PROJECTS" in sec_upper or "EXPERIENCE" in sec_upper:
            if strategy == "skills_only":
                print(f"[GEN] Strategy: skills_only. Skipping rewrite for: {section_name}")
                rewritten[section_name] = sec_data["content"]
            else:
                print(f"[GEN] Tailoring section (bullets mode): {section_name}")
                rewritten[section_name] = rewrite_bullets_with_validation(
                    section_name, sec_data["content"], keywords, context_bank
                )
            continue

        # Fallback for dynamic sections matched by domain focus
        if any(k.lower() in sec_upper.lower() for k in keywords.get("domain_focus", [])):
            if strategy == "skills_only":
                rewritten[section_name] = sec_data["content"]
            else:
                print(f"[GEN] Tailoring section (bullets domain-match): {section_name}")
                rewritten[section_name] = rewrite_bullets_with_validation(
                    section_name, sec_data["content"], keywords, context_bank
                )
        else:
            rewritten[section_name] = sec_data["content"]

    return rewritten
