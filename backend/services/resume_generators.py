import json
import re
from pathlib import Path
from typing import Any
from backend.services.llm_client import get_tailor_client


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
    text = re.sub(
        r"^(?:Here|Sure|Below|Note|Okay|The following)[^\\\n]*\n", "", text, flags=re.MULTILINE | re.IGNORECASE)
    # Remove trailing comments like "% Continue with the rest..."
    text = re.sub(r"^%\s*Continue.*$", "", text,
                  flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"^%\s*Example of.*$", "", text,
                  flags=re.MULTILINE | re.IGNORECASE)
    # Remove templated placeholder snippets that sometimes leak from prompts/JDs.
    text = re.sub(
        r"\[(?:\s*your\s+[^\]]*|\s*e\.g\.,?\s*[^\]]*|\s*for\s+example\s+[^\]]*)\]",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*\\textbf\{\(\s*using\s+[^(){}]{1,120}\)\}|\s*\(\s*using\s+[^()]{1,120}\)",
        "",
        text,
        flags=re.IGNORECASE,
    )
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
        '"required_skills", "required_tools", "action_verbs", "seniority_signals", "domain_focus".'
    )
    client, model_name = get_tailor_client()
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": jd_text}],
            temperature=0.3
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        parsed = json.loads(content)
        if "required_tools" not in parsed:
            parsed["required_tools"] = []
        return parsed
    except Exception:
        return {
            "required_skills": [],
            "required_tools": [],
            "action_verbs": [],
            "seniority_signals": [],
            "domain_focus": [],
        }


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9+#._-]{1,}", text.lower()))


def _project_bullet_payloads(project: dict) -> list[dict]:
    bullets = []
    for key in sorted([k for k in project.keys() if k.startswith("bullet_")]):
        value = project.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    bullets.append(item)
        elif isinstance(value, dict):
            bullets.append(value)

    # New schema support: [[project.achievement]]
    if not bullets:
        achievements = project.get("achievement", [])
        if isinstance(achievements, dict):
            achievements = [achievements]
        if isinstance(achievements, list):
            for entry in achievements:
                if not isinstance(entry, dict):
                    continue
                verb = str(entry.get("verb", "")).strip()
                what = str(entry.get("what", "")).strip()
                built = " ".join(
                    [part for part in [verb, what] if part]).strip()
                bullets.append({
                    "what_did_you_build": built,
                    "tools_used": str(entry.get("tool", "")).strip(),
                    "how_it_works": str(entry.get("outcome", "")).strip(),
                    "metric": str(entry.get("metric", "")).strip(),
                })
    return bullets


def _project_tools_string(project: dict) -> str:
    tools_used = str(project.get("tools_used", "")).strip()
    if tools_used:
        return tools_used

    stack = project.get("stack", [])
    if isinstance(stack, list):
        return ", ".join(str(item).strip() for item in stack if str(item).strip())

    return str(stack).strip()


def _project_fact_text(project: dict) -> str:
    parts = [
        str(project.get("name", "")),
        _project_tools_string(project),
        str(project.get("what_does_it_do", "")),
        str(project.get("summary", "")),
    ]
    for bullet in _project_bullet_payloads(project):
        parts.extend([
            str(bullet.get("what_did_you_build", "")),
            str(bullet.get("tools_used", "")),
            str(bullet.get("how_it_works", "")),
            str(bullet.get("metric", "")),
        ])
    return "\n".join([p for p in parts if p])


def _score_project(project: dict, keywords: dict, original_index: int) -> dict:
    text = _project_fact_text(project)
    project_tokens = _tokenize(text)
    skills = set(_tokenize(" ".join(keywords.get("required_skills", []))))
    tools = set(_tokenize(" ".join(keywords.get("required_tools", []))))
    domain = set(_tokenize(" ".join(keywords.get("domain_focus", []))))

    skill_overlap = (len(project_tokens & skills) /
                     max(1, len(skills))) if skills else 0.0
    tool_overlap = (len(project_tokens & tools) /
                    max(1, len(tools))) if tools else 0.0
    domain_overlap = (len(project_tokens & domain) /
                      max(1, len(domain))) if domain else 0.0
    has_metrics = 1.0 if re.search(r"\b\d+(?:\.\d+)?\b", text) else 0.0

    score = (
        0.45 * skill_overlap +
        0.30 * tool_overlap +
        0.15 * domain_overlap +
        0.10 * has_metrics
    )

    return {
        "name": project.get("name", ""),
        "project": project,
        "score": round(score, 5),
        "index": original_index,
        "features": {
            "skill_overlap": round(skill_overlap, 5),
            "tool_overlap": round(tool_overlap, 5),
            "domain_overlap": round(domain_overlap, 5),
            "metric_bonus": round(has_metrics, 5),
        },
    }


def _llm_tiebreak_order(jd_text: str, tied: list[dict]) -> list[str]:
    if len(tied) < 2:
        return [entry["name"] for entry in tied]

    prompt = {
        "jd_excerpt": jd_text[:3000],
        "projects": [
            {
                "name": entry["name"],
                "tools_used": _project_tools_string(entry["project"]),
                "summary": entry["project"].get("what_does_it_do", "") or entry["project"].get("summary", ""),
            }
            for entry in tied
        ],
    }

    system = (
        "You are ranking candidate projects against a job description. "
        "Return ONLY JSON: {\"ordered_names\": [..]} with names in best-to-worst order."
    )
    client, model_name = get_tailor_client()
    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(prompt)},
            ],
            temperature=0.0,
            max_tokens=220,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content.strip()
        parsed = json.loads(content)
        names = parsed.get("ordered_names", [])
        valid = [name for name in names if any(
            name == entry["name"] for entry in tied)]
        if len(valid) == len(tied):
            return valid
    except Exception:
        pass
    return [entry["name"] for entry in sorted(tied, key=lambda x: x["index"])]


def rank_projects_for_jd(jd_text: str, context_bank: dict, keywords: dict = None) -> tuple[list[dict], dict]:
    if keywords is None:
        keywords = extract_jd_keywords(jd_text)
    projects = context_bank.get("project", [])
    scored = [_score_project(project, keywords, idx)
              for idx, project in enumerate(projects)]
    scored.sort(key=lambda item: (-item["score"], item["index"]))

    i = 0
    while i < len(scored):
        j = i + 1
        while j < len(scored) and abs(scored[j]["score"] - scored[i]["score"]) <= 0.10:
            j += 1
        if j - i > 1:
            tied_group = scored[i:j]
            tiebroken_names = _llm_tiebreak_order(jd_text, tied_group)
            order_map = {name: pos for pos, name in enumerate(tiebroken_names)}
            scored[i:j] = sorted(
                tied_group,
                key=lambda item: order_map.get(item["name"], 999),
            )
        i = j

    diagnostics = {
        "keywords": keywords,
        "ranked": [
            {
                "name": item["name"],
                "score": item["score"],
                "features": item["features"],
            }
            for item in scored
        ],
    }
    return scored, diagnostics


def _escape_latex_text(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    out = []
    for ch in text:
        out.append(replacements.get(ch, ch))
    return "".join(out)


def _project_to_bullets(project: dict, max_bullets: int = 3) -> str:
    lines = []
    for payload in _project_bullet_payloads(project):
        built = str(payload.get("what_did_you_build", "")).strip()
        tool = str(payload.get("tools_used", "")).strip()
        how = str(payload.get("how_it_works", "")).strip()
        metric = str(payload.get("metric", "")).strip()

        sentence = built
        if tool and sentence and " using " not in sentence.lower():
            sentence = f"{sentence} using {tool}"
        if how:
            sentence = f"{sentence}, {how}" if sentence else how
        if metric:
            sentence = f"{sentence}, achieving {metric}" if sentence else metric
        sentence = re.sub(r"\s+", " ", sentence).strip()
        sentence = sentence.strip(" .;,")
        if sentence:
            sentence = sentence + "."
        if sentence:
            lines.append(rf"\bitem{{{_escape_latex_text(sentence)}}}")
        if len(lines) >= max_bullets:
            break
    return "\n".join(lines)


def _project_keyword_candidates(keywords: dict) -> list[str]:
    generic = {
        "software", "engineer", "intern", "internship", "development",
        "web", "application", "applications", "platform", "systems", "system",
    }
    values: list[str] = []
    for key in ("required_skills", "required_tools", "domain_focus"):
        raw = keywords.get(key, [])
        if isinstance(raw, list):
            values.extend(str(item).strip()
                          for item in raw if str(item).strip())

    ordered_unique: list[str] = []
    seen = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        lowered = normalized.lower()
        if len(normalized) < 3 or lowered in generic:
            continue
        if lowered not in seen:
            seen.add(lowered)
            ordered_unique.append(normalized)

    return sorted(
        ordered_unique,
        key=lambda item: (-len(item.split()), -len(item), item.lower()),
    )


def _apply_keyword_bolding_to_project_bullets(
    bullets: str,
    keywords: dict,
    max_bold_per_bullet: int = 2,
) -> str:
    candidates = _project_keyword_candidates(keywords)
    if not candidates:
        return bullets

    def _bold_once(text: str, phrase: str) -> tuple[str, bool]:
        phrase_pattern = re.escape(phrase).replace(r"\ ", r"\s+")
        phrase_pattern = phrase_pattern.replace(r"\#", r"(?:\\#|#)")
        pattern = re.compile(
            rf"(?<![A-Za-z0-9])({phrase_pattern})(?![A-Za-z0-9])",
            flags=re.IGNORECASE,
        )
        updated, count = pattern.subn(
            lambda m: rf"\textbf{{{m.group(1)}}}", text, count=1)
        return updated, count > 0

    result_lines = []
    for line in bullets.splitlines():
        if "\\bitem{" not in line:
            result_lines.append(line)
            continue

        hidden_segments = []

        def _hide_existing_bold(match: re.Match) -> str:
            hidden_segments.append(match.group(0))
            return f"__EXISTING_BOLD_{len(hidden_segments) - 1}__"

        working = re.sub(r"\\textbf\{[^{}]*\}", _hide_existing_bold, line)
        bolded = 0
        for phrase in candidates:
            if bolded >= max_bold_per_bullet:
                break
            working, changed = _bold_once(working, phrase)
            if changed:
                bolded += 1

        for idx, original in enumerate(hidden_segments):
            working = working.replace(f"__EXISTING_BOLD_{idx}__", original)

        result_lines.append(working)

    return "\n".join(result_lines)


def build_ranked_projects_section(job_description: str, context_bank: dict, strategy: str = "full_rewrite", keywords: dict = None) -> tuple[str, dict]:
    ranked, diagnostics = rank_projects_for_jd(
        job_description, context_bank, keywords=keywords)
    selected = ranked[:3]
    diagnostics["selected_projects"] = [item["name"] for item in selected]

    blocks = []
    for item in selected:
        project = item["project"]
        section_name = f"PROJECTS: {project.get('name', 'Project')}"
        bullets = _project_to_bullets(project, max_bullets=3)

        if strategy != "skills_only" and bullets.strip():
            rewritten = rewrite_bullets_with_validation(
                section_name=section_name,
                current_text=bullets,
                keywords=diagnostics["keywords"],
                context_bank=context_bank,
            )
            bullets = rewritten if rewritten.strip() else bullets

        bullets = _apply_keyword_bolding_to_project_bullets(
            bullets,
            diagnostics["keywords"],
            max_bold_per_bullet=2,
        )

        heading_name = _escape_latex_text(str(project.get("name", "Project")))
        heading_tools = _escape_latex_text(_project_tools_string(project))
        heading_date = _escape_latex_text(
            str(project.get("dates") or project.get("date") or "")
        )

        block = (
            "  \\projectheading\n"
            f"    {{\\textbf{{{heading_name}}}\n"
            f"     $\\,|\\,$ \\textit{{{heading_tools}}}}}\n"
            f"    {{{heading_date}}}\n"
            "  \\bulletListStart\n"
            f"{bullets}\n"
            "  \\bulletListEnd"
        )
        blocks.append(block)

    section_text = "\\section{Projects}\n\n\\outerListStart\n\n"
    section_text += "\n\n".join(blocks)
    section_text += "\n\n\\outerListEnd\n"

    return section_text, diagnostics


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
                                fragments.append(
                                    "\n".join(f"  {k}: {v}" for k, v in p.items()))
                        elif isinstance(proj, dict):
                            fragments.append(
                                "\n".join(f"  {k}: {v}" for k, v in proj.items()))

    if section_name.upper().startswith("PROJECTS:"):
        project_hint = section_name.split(":", 1)[1].strip().lower()
        for proj in context_bank.get("project", []):
            if project_hint in proj.get("name", "").lower():
                fragments.append(
                    "\n".join(f"  {k}: {v}" for k, v in proj.items()))

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
- Do NOT output placeholder snippets like "[your stack: ...]", "[e.g., ...]", or any bracketed sample text.

TENSE & GRAMMAR LOCK (CRITICAL):
- You MUST maintain the EXACT tense of the original bullet.
- If the original uses past tense ("Architected", "Built", "Designed"),
  the tailored version MUST remain past tense.
- Do NOT blindly copy present-tense verbs from the job description.

OWNERSHIP LANGUAGE (CRITICAL):
- Do NOT use weak ownership phrasing like "assist", "assisted", "helped", or "supported".
- Use direct ownership verbs that reflect authorship (e.g., "Built", "Developed", "Designed", "Implemented", "Led").
- If the source bullet begins with weak ownership phrasing, rewrite it to strong ownership phrasing while preserving facts and metrics.

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

    client, model_name = get_tailor_client()
    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user_msg}],
        temperature=0.5
    )
    return sanitize_llm_latex(resp.choices[0].message.content.strip())


def _display_category_name(raw_key: str) -> str:
    key = raw_key.strip().upper()
    mapping = {
        "BACKEND_FRAMEWORKS": "Backend Frameworks",
        "APIS_PROTOCOLS": "APIs & Protocols",
        "DEVOPS_TOOLS": "DevOps Tools",
        "FRONTEND_MOBILE": "Frontend & Mobile",
        "ML_FRAMEWORKS": "ML Frameworks",
        "LLM_TECH": "LLM Tech",
        "VECTOR_DATABASES": "Vector Databases",
        "RAG_CONCEPTS": "RAG Concepts",
        "NLP_TOOLS": "NLP Tools",
        "DATA_COLLECTION": "Data Collection",
        "CORE_AI": "Core AI",
        "AGENTIC_TOOLS": "Agentic Tools",
    }
    if key in mapping:
        return mapping[key]
    return " ".join(part.capitalize() for part in key.split("_"))


def _normalize_skill_token(value: str) -> str:
    token = value.strip().lower()
    token = re.sub(r"\([^)]*\)", "", token)
    token = re.sub(r"[^a-z0-9+#._\-/\s]", " ", token)
    token = re.sub(r"\s+", " ", token).strip()
    return token


def _parse_master_skills_bank(skills_md: str) -> dict[str, set[str]]:
    """Parse skills.md into canonical category names with normalized skill tokens."""
    categories: dict[str, set[str]] = {}
    for line in skills_md.splitlines():
        match = re.match(r"^([A-Z_]+):\s*(.+)$", line.strip())
        if not match:
            continue
        display = _display_category_name(match.group(1))
        skills = [item.strip()
                  for item in match.group(2).split(",") if item.strip()]
        normalized = {_normalize_skill_token(item) for item in skills}
        normalized = {item for item in normalized if item}
        if normalized:
            categories[display] = normalized
    return categories


def _canonicalize_skills_categories(skills_tex: str, skills_md: str, fallback_text: str) -> str:
    """Normalize LLM-generated skills headings to canonical skills.md category names."""
    bank = _parse_master_skills_bank(skills_md)
    if not bank:
        return skills_tex

    canonical_names = {name.lower(): name for name in bank.keys()}
    normalized_lines = []

    for raw_line in [line.strip() for line in skills_tex.splitlines() if line.strip()]:
        line_match = re.match(
            r"^\\textbf\{(?P<cat>[^:}]+):\}\s*(?P<skills>.*?)(?P<suffix>\\\\\[2pt\])?$",
            raw_line,
        )
        if not line_match:
            return fallback_text

        raw_category = line_match.group("cat").strip()
        raw_skills = line_match.group("skills").strip()
        suffix = line_match.group("suffix") or ""

        category_key = raw_category.lower()
        if category_key in canonical_names:
            chosen_category = canonical_names[category_key]
        else:
            generated_tokens = {
                _normalize_skill_token(item)
                for item in raw_skills.split(",")
                if _normalize_skill_token(item)
            }
            chosen_category = None
            best_overlap = -1
            for canonical_category, canonical_tokens in bank.items():
                overlap = len(generated_tokens & canonical_tokens)
                if overlap > best_overlap:
                    best_overlap = overlap
                    chosen_category = canonical_category

            if not chosen_category:
                return fallback_text

        normalized_lines.append(
            rf"\textbf{{{chosen_category}:}} {raw_skills}{suffix}"
        )

    return "\n".join(normalized_lines)


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
- Do NOT output placeholder snippets like "[your stack: ...]", "[e.g., ...]", or any bracketed sample text.

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

    client, model_name = get_tailor_client()
    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user_msg}],
        temperature=0.4
    )
    result = sanitize_llm_latex(resp.choices[0].message.content.strip())

    # Safety net: if the LLM still produced \bitem, reject and keep original
    if r"\bitem" in result:
        print(
            f"[GUARD] Skills rewriter produced bullet points — rejecting, keeping original.")
        return current_text

    return _canonicalize_skills_categories(result, skills_md, current_text)


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
        output = rewrite_bullets(
            section_name, current_text, keywords, context_bank, is_retry)
        output_numbers = extract_numbers(output)

        hallucinated = output_numbers - true_numbers
        if hallucinated:
            print(
                f"[GUARD] LLM invented number(s) {hallucinated} in section '{section_name}'")
            if attempt == 0:
                continue
            else:
                return current_text  # Fallback to original on double-fail
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

    client, model_name = get_tailor_client()
    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user_msg}],
        temperature=0.3
    )
    return sanitize_llm_latex(resp.choices[0].message.content.strip())


def generate_tailored_content(job_description: str, sections: dict, context_bank: dict, strategy: str = "full_rewrite", keywords: dict = None) -> dict:
    """
    The orchestrator for section-by-section content generation.
    Decides based on section name which rewriter (Skills vs Bullets) to use.

    Args:
        job_description (str): Full JD text.
        sections (dict): Parsed LaTeX sections from the template.
        context_bank (dict): Master profile data.
        strategy (str): 'full_rewrite' or 'skills_only'.
        keywords (dict, optional): Pre-extracted JD keywords. If None, extracted internally.

    Returns:
        dict: Mapping of section names to their tailored content strings.
    """
    desc = job_description
    if len(desc) > 8000:
        desc = desc[:8000]  # Truncate massive JDs for token efficiency

    if keywords is None:
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
                print(
                    f"[GEN] Strategy: skills_only. Skipping rewrite for: {section_name}")
                rewritten[section_name] = sec_data["content"]
            else:
                print(
                    f"[GEN] Tailoring section (bullets mode): {section_name}")
                rewritten[section_name] = rewrite_bullets_with_validation(
                    section_name, sec_data["content"], keywords, context_bank
                )
            continue

        # Fallback for dynamic sections matched by domain focus
        if any(k.lower() in sec_upper.lower() for k in keywords.get("domain_focus", [])):
            if strategy == "skills_only":
                rewritten[section_name] = sec_data["content"]
            else:
                print(
                    f"[GEN] Tailoring section (bullets domain-match): {section_name}")
                rewritten[section_name] = rewrite_bullets_with_validation(
                    section_name, sec_data["content"], keywords, context_bank
                )
        else:
            rewritten[section_name] = sec_data["content"]

    return rewritten
