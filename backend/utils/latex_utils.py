import re

_FORBIDDEN_PARENTHESES_PHRASES = {
    "improving research",
    "improve research",
}

_BRACKET_PLACEHOLDER_PATTERN = re.compile(
    r"\\textbf\{\[(?:\s*your\s+[^\]]*|\s*e\.g\.,?\s*[^\]]*|\s*for\s+example\s+[^\]]*)\]\}"
    r"|\[(?:\s*your\s+[^\]]*|\s*e\.g\.,?\s*[^\]]*|\s*for\s+example\s+[^\]]*)\]",
    flags=re.IGNORECASE,
)

_USING_PARENTHESES_PATTERN = re.compile(
    r"\s*\\textbf\{\(\s*using\s+[^(){}]{1,120}\)\}|\s*\(\s*using\s+[^()]{1,120}\)",
    flags=re.IGNORECASE,
)

_OWNERSHIP_WEAK_PHRASE_REPLACEMENTS = (
    (re.compile(
        r"\bA\s+\\textbf\{\s*contribute\s+to\s*\}", re.IGNORECASE), "Developed"),
    (re.compile(r"\bA\s+contribute\s+to\b", re.IGNORECASE), "Developed"),
    (re.compile(r"\bassist(?:ed)?\s+in\s+building\s+and\s+maintaining\b",
     re.IGNORECASE), "Built and maintained"),
    (re.compile(r"\bassist(?:ed)?\s+in\s+developing\s+and\s+maintaining\b",
     re.IGNORECASE), "Developed and maintained"),
    (re.compile(r"\bassist(?:ed)?\s+in\s+building\b", re.IGNORECASE), "Built"),
    (re.compile(r"\bassist(?:ed)?\s+in\s+developing\b", re.IGNORECASE), "Developed"),
    (re.compile(r"\bassist(?:ed)?\s+in\s+designing\b", re.IGNORECASE), "Designed"),
    (re.compile(r"\bassist(?:ed)?\s+in\s+implementing\b", re.IGNORECASE), "Implemented"),
    (re.compile(r"\bassist(?:ed)?\s+with\b", re.IGNORECASE), "Contributed to"),
    (re.compile(r"\bhelp(?:ed)?\s+build\b", re.IGNORECASE), "Built"),
    (re.compile(r"\bhelp(?:ed)?\s+develop\b", re.IGNORECASE), "Developed"),
    (re.compile(r"\bsupport(?:ed)?\s+the\s+development\s+of\b", re.IGNORECASE), "Developed"),
    (re.compile(r"\bcontribut(?:e|ed)\s+to\b", re.IGNORECASE), "Built"),
    (re.compile(r"\bparticipat(?:e|ed)\s+in\b", re.IGNORECASE), "Developed"),
    (re.compile(r"\bengag(?:e|ed)\s+in\b", re.IGNORECASE), "Developed"),
    (re.compile(r"\bdocument\s+and\s+maintain\b",
     re.IGNORECASE), "Documented and maintained"),
    (re.compile(r"\bdevelop\s+a\b", re.IGNORECASE), "Developed a"),
)


def _trim_visible_text_to_limit(text: str, max_chars: int) -> str:
    """Trim text at semantic boundaries to stay within max visible chars."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= max_chars:
        return collapsed

    # Prefer complete clause boundaries first.
    clauses = re.split(r"([.;])", collapsed)
    rebuilt = ""
    i = 0
    while i < len(clauses):
        part = clauses[i].strip()
        sep = clauses[i + 1] if i + 1 < len(clauses) else ""
        candidate = (rebuilt + " " + part + sep).strip()
        if candidate and len(candidate) <= max_chars:
            rebuilt = candidate
            i += 2
            continue
        break

    if rebuilt:
        return rebuilt.rstrip(".;, ") + "."

    # Fallback: trim by complete word boundary, never mid-word.
    head = collapsed[:max_chars + 1]
    if len(head) <= max_chars:
        return head
    last_space = head.rfind(" ")
    if last_space <= 0:
        return collapsed[:max_chars].rstrip(".;, ") + "."
    return head[:last_space].rstrip(".;, ") + "."


def _extract_bitem_payloads(tex_content: str) -> list[str]:
    """Extract raw payload text inside each \bitem{...} block using brace balancing."""
    payloads = []
    marker = "\\bitem{"
    idx = 0
    while True:
        start = tex_content.find(marker, idx)
        if start == -1:
            break

        cursor = start + len(marker)
        depth = 1
        chunk = []
        while cursor < len(tex_content) and depth > 0:
            ch = tex_content[cursor]
            if ch == "{" and (cursor == 0 or tex_content[cursor - 1] != "\\"):
                depth += 1
                chunk.append(ch)
            elif ch == "}" and (cursor == 0 or tex_content[cursor - 1] != "\\"):
                depth -= 1
                if depth > 0:
                    chunk.append(ch)
            else:
                chunk.append(ch)
            cursor += 1

        if depth == 0:
            payloads.append("".join(chunk))
        idx = cursor
    return payloads


def _visible_text_from_latex(text: str) -> str:
    """Convert a LaTeX bullet payload into approximated visible plain text."""
    visible = text
    visible = re.sub(r"\\textbf\{([^{}]*)\}", r"\1", visible)
    visible = re.sub(r"\\textit\{([^{}]*)\}", r"\1", visible)
    visible = re.sub(r"\\href\{[^{}]*\}\{([^{}]*)\}", r"\1", visible)
    visible = re.sub(
        r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?", " ", visible)
    visible = visible.replace("{", " ").replace("}", " ")
    visible = visible.replace(r"\%", "%").replace(r"\&", "&")
    visible = visible.replace(r"\_", "_").replace(r"\$", "$")
    visible = re.sub(r"\s+", " ", visible).strip()
    return visible


def _extract_bitem_payload_spans(tex_content: str) -> list[tuple[int, int, str]]:
    """Return payload spans for each \bitem{...} as (start, end, payload)."""
    spans = []
    marker = "\\bitem{"
    idx = 0

    while True:
        start = tex_content.find(marker, idx)
        if start == -1:
            break

        payload_start = start + len(marker)
        cursor = payload_start
        depth = 1
        chunk = []
        while cursor < len(tex_content) and depth > 0:
            ch = tex_content[cursor]
            if ch == "{" and (cursor == 0 or tex_content[cursor - 1] != "\\"):
                depth += 1
                chunk.append(ch)
            elif ch == "}" and (cursor == 0 or tex_content[cursor - 1] != "\\"):
                depth -= 1
                if depth > 0:
                    chunk.append(ch)
            else:
                chunk.append(ch)
            cursor += 1

        if depth == 0:
            payload_end = cursor - 1
            spans.append((payload_start, payload_end, "".join(chunk)))
        idx = cursor

    return spans


def _escape_latex_inline(text: str) -> str:
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
    return "".join(replacements.get(ch, ch) for ch in text)


def _normalize_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _sanitize_forbidden_parentheses(text: str) -> str:
    """Strip known forbidden parenthetical phrases that may leak from JD text."""
    sanitized = text
    for phrase in _FORBIDDEN_PARENTHESES_PHRASES:
        escaped = re.escape(phrase)
        sanitized = re.sub(
            rf"\s*\\textbf\{{\({escaped}\)\}}",
            "",
            sanitized,
            flags=re.IGNORECASE,
        )
        sanitized = re.sub(
            rf"\s*\({escaped}\)",
            "",
            sanitized,
            flags=re.IGNORECASE,
        )
    return sanitized


def _sanitize_bracket_placeholders(text: str) -> str:
    """Strip bracketed template placeholders that are not valid resume content."""
    return _BRACKET_PLACEHOLDER_PATTERN.sub("", text)


def _sanitize_using_parenthetical_labels(text: str) -> str:
    """Strip parenthetical 'using ...' labels injected by LLMs inside bullets."""
    return _USING_PARENTHESES_PATTERN.sub("", text)


def _enforce_ownership_language(text: str) -> str:
    """Normalize weak ownership wording into direct ownership phrasing."""
    normalized = text
    for pattern, replacement in _OWNERSHIP_WEAK_PHRASE_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def _strip_trailing_bold_parenthetical_tag(line: str) -> str:
    """Remove stylistic JD tags like '\\textbf{(Full Stack Development)}' at bullet end."""
    if "\\bitem{" not in line:
        return line

    pattern = re.compile(
        r"(?P<prefix>\\bitem\{.*?)(?P<tag>\s*\\textbf\{\((?P<phrase>[^{}()]{2,80})\)\})(?P<suffix>\s*\}\s*)$"
    )
    match = pattern.search(line)
    if not match:
        return line

    phrase = _normalize_phrase(match.group("phrase"))
    has_digit = bool(re.search(r"\d", phrase))
    word_count = len([w for w in re.split(r"[\s,]+", phrase) if w])
    if not has_digit and 1 <= word_count <= 7:
        return f"{match.group('prefix')}{match.group('suffix')}"
    return line


def _sanitize_tailored_content(content: dict) -> dict:
    """Best-effort cleanup for occasional LLM leakage into tailored bullet text."""
    cleaned = {}
    for section_name, section_text in content.items():
        section_cleaned = _sanitize_forbidden_parentheses(section_text)
        section_cleaned = _sanitize_bracket_placeholders(section_cleaned)
        section_cleaned = _sanitize_using_parenthetical_labels(section_cleaned)
        section_cleaned = _enforce_ownership_language(section_cleaned)
        if any(k in section_name.upper() for k in ("EXPERIENCE", "PROJECT")):
            lines = section_cleaned.splitlines()
            lines = [_strip_trailing_bold_parenthetical_tag(
                line) for line in lines]
            section_cleaned = "\n".join(lines)
        cleaned[section_name] = section_cleaned
    return cleaned


def _sanitize_tex_string(tex_string: str) -> str:
    """Final defensive scrub before writing/compiling generated LaTeX."""
    text = _sanitize_forbidden_parentheses(tex_string)
    text = _sanitize_bracket_placeholders(text)
    text = _sanitize_using_parenthetical_labels(text)
    text = _enforce_ownership_language(text)
    lines = text.splitlines()
    lines = [_strip_trailing_bold_parenthetical_tag(line) for line in lines]
    return "\n".join(lines)
