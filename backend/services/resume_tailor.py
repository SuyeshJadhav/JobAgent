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
from backend.services.resume_generators import (
    extract_jd_keywords,
    generate_tailored_content,
    trim_bullets,
    build_ranked_projects_section,
)

ROOT_DIR = Path(__file__).parent.parent.parent
REFERENCES_DIR = ROOT_DIR / "references"
OUTPUT_DIR = ROOT_DIR / "outputs" / "applications"

BASE_RESUME = REFERENCES_DIR / "main.tex"
CONTEXT_BANK = REFERENCES_DIR / "context_bank.toml"

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

_VALIDATOR_ACTION_VERBS = {
    "architected", "automated", "built", "constructed", "created", "debugged",
    "delivered", "deployed", "designed", "developed", "diagnosed", "drove",
    "enabled", "engineered", "established", "implemented", "improved",
    "integrated", "launched", "led", "maintained", "optimized", "orchestrated",
    "owned", "profiled", "reduced", "refactored", "scaled", "shipped",
    "streamlined", "validated", "wrote",
}

_VALIDATOR_WEAK_OWNERSHIP_PATTERN = re.compile(
    r"\b(?:assist(?:ed|ing)?|help(?:ed|ing)?|support(?:ed|ing)?|"
    r"contribut(?:e|ed|ing)|worked\s+on|collaborat(?:e|ed|ing))\b",
    flags=re.IGNORECASE,
)

_VALIDATOR_PLACEHOLDER_PATTERN = re.compile(
    r"\[\s*your\s+stack[^\]]*\]",
    flags=re.IGNORECASE,
)

_VALIDATOR_BULLET_MAX_VISIBLE_CHARS = 200

_VALIDATOR_COMMON_TOOL_TERMS = {
    "angular", "aws", "azure", "c", "c++", "c#", "chroma", "chromadb",
    "codecov", "css", "detectgpt", "d3.js", "docker", "express", "fastapi",
    "firebase", "flask", "flutter", "gemini", "github actions", "go", "golang",
    "groq", "html", "java", "javascript", "jest", "jwt", "keybert", "kubernetes",
    "llama", "mongodb", "mysql", "next.js", "node", "node.js", "ollama",
    "openai", "postgresql", "pydantic", "pytest", "python", "pytorch", "react",
    "react native", "redis", "rest api", "rest apis", "roberta", "sentence-transformers",
    "socket.io", "sql", "sqlite", "tailwind", "tensorflow", "tf-idf", "typescript",
    "umap", "whisper",
}

TOOL_ALIASES = {
    "node": "node.js",
    "nodejs": "node.js",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "mysql": "mysql",
    "tensorflow": "tensorflow",
    "react": "react",
    "ts": "typescript",
    "js": "javascript",
    "py": "python",
    "k8s": "kubernetes",
    "tf": "tensorflow",
    "torch": "pytorch",
}

BULLET_TEMPLATES = [
    "{verb} {what} using {tool}, achieving {metric}.",
    "{verb} {what} using {tool} to {outcome}.",
    "{verb} {what} to {outcome}, reducing {metric}.",
    "{verb} {what} with {tool}, achieving {metric}.",
    "{verb} {what} using {tool}, enabling {outcome}.",
]

WEAK_STARTERS = {
    "assisted", "helped", "supported", "contributed",
    "worked", "collaborated", "participated", "aided"
}

ACTION_VERB_ALLOWLIST = {
    "built", "developed", "implemented", "designed",
    "architected", "engineered", "optimized", "reduced",
    "improved", "automated", "deployed", "migrated",
    "refactored", "integrated", "created", "established",
    "launched", "delivered", "shipped", "scaled",
    "led", "drove", "achieved", "eliminated"
}

DETERMINISTIC_SECTIONS = {
    "PROJECTS",
    "EXPERIENCE",
}

METRIC_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(ms|sec|s|min|hrs?|%|x|X|"
    r"tokens?/sec|texts?/sec|req/sec|"
    r"queries/sec|users?|records?|"
    r"endpoints?|tools?|stages?|"
    r"components?|k|K|M|GB|MB)",
    flags=re.IGNORECASE,
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


def _extract_metric(text: str) -> str:
    """Extract the first compact numeric metric token from free-form text."""
    if not text:
        return ""
    matches = METRIC_PATTERN.findall(text)
    if not matches:
        return ""
    number, unit = matches[0]
    return f"{number}{unit}"


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


def _normalize_tool_term(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = normalized.strip(" .;:|()[]{}")
    return normalized


def _canonicalize_tool_term(value: str) -> str:
    normalized = _normalize_tool_term(value)
    return TOOL_ALIASES.get(normalized, normalized)


def _extract_tool_terms_from_text(raw_value: str) -> set[str]:
    terms = set()
    if not raw_value:
        return terms

    candidate = raw_value.strip()
    if candidate:
        terms.add(_normalize_tool_term(candidate))

    for comma_split in re.split(r"[,;]", raw_value):
        part = comma_split.strip()
        if not part:
            continue
        terms.add(_normalize_tool_term(part))

        for paren_text in re.findall(r"\(([^()]*)\)", part):
            for nested in paren_text.split(","):
                nested_term = _normalize_tool_term(nested)
                if nested_term:
                    terms.add(nested_term)

        for slash_split in part.split("/"):
            slash_term = _normalize_tool_term(slash_split)
            if slash_term:
                terms.add(slash_term)

    return {term for term in terms if term and len(term) >= 2}


def _collect_context_bank_tool_terms(context_bank: dict) -> set[str]:
    """Collect normalized tool terms from context_bank tool fields across schemas."""
    terms = set()

    def _walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"tools_used", "tool"}:
                    if isinstance(value, str):
                        terms.update(_extract_tool_terms_from_text(value))
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                terms.update(
                                    _extract_tool_terms_from_text(item))
                elif key == "stack":
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, str):
                                terms.update(
                                    _extract_tool_terms_from_text(item))
                    elif isinstance(value, str):
                        terms.update(_extract_tool_terms_from_text(value))
                else:
                    _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(context_bank)
    return {_canonicalize_tool_term(term) for term in terms if term}


def _collect_context_bank_numbers(context_bank: dict) -> set[str]:
    raw = json.dumps(context_bank, ensure_ascii=False)
    return set(re.findall(r"\b\d+(?:\.\d+)?\b", raw))


def _extract_first_word_for_action_check(visible_text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z+#.-]*", visible_text)
    if not words:
        return ""

    first = words[0].lower()
    if first in {"a", "an", "the"} and len(words) > 1:
        return words[1].lower()
    if first.endswith("ly") and len(words) > 1:
        return words[1].lower()
    return first


def _find_tool_mentions(visible_text: str, candidates: set[str]) -> set[str]:
    found = set()
    if not visible_text:
        return found

    visible = visible_text.lower()

    for term in sorted(candidates, key=len, reverse=True):
        canonical_term = _canonicalize_tool_term(term)
        escaped = re.escape(canonical_term).replace(r"\ ", r"\\s+")
        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])",
            flags=re.IGNORECASE,
        )
        if pattern.search(visible):
            found.add(canonical_term)

        alias_terms = [alias for alias,
                       target in TOOL_ALIASES.items() if target == canonical_term]
        for alias in alias_terms:
            if len(alias) <= 2:
                alias_pattern = re.compile(
                    rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9-])",
                    flags=re.IGNORECASE,
                )
            else:
                alias_pattern = re.compile(
                    rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])",
                    flags=re.IGNORECASE,
                )
            if alias_pattern.search(visible):
                found.add(canonical_term)
                break
    return found


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


def _tokenize_text(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9+#._-]{1,}", text.lower()))


def _keyword_token_set(keywords: dict | None) -> set[str]:
    if not isinstance(keywords, dict):
        return set()
    values = []
    for key in ("required_skills", "required_tools", "domain_focus", "action_verbs"):
        raw = keywords.get(key, [])
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return _tokenize_text(" ".join(values))


def _experience_entries_from_context(context_bank: dict) -> list[dict]:
    entries = []
    for exp in context_bank.get("experience", []):
        facts = []

        achievements = exp.get("achievement", [])
        if isinstance(achievements, dict):
            achievements = [achievements]
        if isinstance(achievements, list):
            for idx, ach in enumerate(achievements):
                if not isinstance(ach, dict):
                    continue
                verb = str(ach.get("verb", "")).strip()
                what = str(ach.get("what", "")).strip()
                facts.append({
                    "what": what,
                    "tool": str(ach.get("tool", "")).strip(),
                    "metric": _extract_metric(str(ach.get("metric", ""))),
                    "outcome": str(ach.get("outcome", "")).strip(),
                    "action": verb,
                    "ordinal": idx,
                })

        if not facts:
            for key, value in exp.items():
                if not key.startswith("project_"):
                    continue
                raw_entries = value if isinstance(value, list) else [value]
                for idx, item in enumerate(raw_entries):
                    if not isinstance(item, dict):
                        continue
                    action = str(item.get("your_specific_role", "")).strip()
                    what = str(item.get("what_did_you_build", "")).strip()
                    facts.append({
                        "what": what,
                        "tool": str(item.get("tools_used", "")).strip(),
                        "metric": _extract_metric(str(
                            item.get("metric")
                            or item.get("after_your_work")
                            or item.get("scale")
                            or ""
                        )),
                        "outcome": str(
                            item.get("what_problem_it_solved")
                            or item.get("after_your_work")
                            or ""
                        ).strip(),
                        "action": action,
                        "ordinal": idx,
                    })

        entries.append({
            "company": str(exp.get("company", "")).strip(),
            "role": str(exp.get("role", "")).strip(),
            "dates": str(exp.get("dates", "")).strip(),
            "location": str(exp.get("location", "")).strip(),
            "facts": [fact for fact in facts if fact.get("what")],
        })
    return entries


def _score_fact_for_jd(fact: dict, keyword_tokens: set[str]) -> float:
    if not keyword_tokens:
        return 0.0
    fact_text = " ".join([
        fact.get("what", ""),
        fact.get("tool", ""),
        fact.get("outcome", ""),
        fact.get("metric", ""),
        fact.get("action", ""),
    ])
    tokens = _tokenize_text(fact_text)
    if not tokens:
        return 0.0
    overlap = len(tokens & keyword_tokens)
    density = overlap / max(1, len(keyword_tokens))
    metric_bonus = 0.05 if fact.get("metric") else 0.0
    return density + metric_bonus


def _build_deterministic_experience_section(
    context_bank: dict,
    jd_keywords: dict,
) -> tuple[str, dict]:
    entries = _experience_entries_from_context(context_bank)
    keyword_tokens = _keyword_token_set(jd_keywords)
    diagnostics = {"selected_achievements": {}}

    blocks = ["\\section{Experience}", "", "\\outerListStart", ""]

    for entry in entries:
        company = _escape_latex_inline(entry.get("company", ""))
        dates = _escape_latex_inline(entry.get("dates", ""))
        role = _escape_latex_inline(entry.get("role", ""))
        location = _escape_latex_inline(entry.get("location", ""))

        blocks.extend([
            "  \\subheading",
            f"    {{{company}}}{{{dates}}}",
            f"    {{{role}}}{{{location}}}",
            "  \\bulletListStart",
        ])

        facts = entry.get("facts", [])
        ranked = sorted(
            facts,
            key=lambda fact: (-_score_fact_for_jd(fact,
                              keyword_tokens), fact.get("ordinal", 0)),
        )
        selected = ranked[:3]
        diagnostics["selected_achievements"][entry.get("company", "Unknown")] = [
            {
                "what": fact.get("what", ""),
                "tool": fact.get("tool", ""),
                "metric": fact.get("metric", ""),
            }
            for fact in selected
        ]

        for fact in selected:
            payload = _render_deterministic_template_bullet(fact)
            if not payload:
                continue
            blocks.append(f"    \\bitem{{{payload}}}")

        blocks.extend([
            "  \\bulletListEnd",
            "",
        ])

    blocks.append("\\outerListEnd")
    blocks.append("")
    return "\n".join(blocks), diagnostics


def _build_context_fact_pool(context_bank: dict) -> list[dict]:
    """Build deterministic fact candidates from context_bank only."""
    facts = []

    def _append_fact(verb: str, what: str, tool: str, metric: str, outcome: str, action: str):
        facts.append({
            "verb": str(verb).strip() if verb else "",
            "what": str(what).strip() if what else "",
            "tool": str(tool).strip() if tool else "",
            "metric": _extract_metric(str(metric or "")),
            "outcome": str(outcome).strip() if outcome else "",
            "action": str(action).strip() if action else "",
        })

    for exp in context_bank.get("experience", []):
        # New schema support: [[experience.achievement]]
        achievements = exp.get("achievement", [])
        if isinstance(achievements, dict):
            achievements = [achievements]
        for entry in achievements if isinstance(achievements, list) else []:
            if not isinstance(entry, dict):
                continue
            _append_fact(
                verb=str(entry.get("verb", "")),
                what=str(entry.get("what", "")),
                tool=str(entry.get("tool", "")),
                metric=str(entry.get("metric", "")),
                outcome=str(entry.get("outcome", "")),
                action=str(entry.get("verb", "")),
            )

        # Legacy schema support.
        for key, value in exp.items():
            if not key.startswith("project_"):
                continue
            entries = value if isinstance(value, list) else [value]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                _append_fact(
                    verb=str(entry.get("your_specific_role", "")),
                    what=str(entry.get("what_did_you_build", "")),
                    tool=str(entry.get("tools_used", "")),
                    metric=str(
                        entry.get("metric")
                        or entry.get("after_your_work")
                        or entry.get("scale")
                        or ""
                    ),
                    outcome=str(
                        entry.get("what_problem_it_solved")
                        or entry.get("after_your_work")
                        or ""
                    ),
                    action=str(entry.get("your_specific_role", "")),
                )

    for proj in context_bank.get("project", []):
        project_tool = str(proj.get("tools_used", "")).strip()
        if not project_tool:
            stack = proj.get("stack", [])
            if isinstance(stack, list):
                project_tool = ", ".join(str(item).strip()
                                         for item in stack if str(item).strip())
            elif isinstance(stack, str):
                project_tool = stack.strip()

        project_outcome = str(proj.get("what_does_it_do", "")).strip() or str(
            proj.get("summary", "")).strip()

        # New schema support: [[project.achievement]]
        achievements = proj.get("achievement", [])
        if isinstance(achievements, dict):
            achievements = [achievements]
        for entry in achievements if isinstance(achievements, list) else []:
            if not isinstance(entry, dict):
                continue
            _append_fact(
                verb=str(entry.get("verb", "")),
                what=str(entry.get("what", "")),
                tool=str(entry.get("tool") or project_tool or ""),
                metric=str(entry.get("metric", "")),
                outcome=str(entry.get("outcome") or project_outcome or ""),
                action=str(entry.get("verb", "")),
            )

        # Legacy schema support.
        for key, value in proj.items():
            if not key.startswith("bullet_"):
                continue
            entries = value if isinstance(value, list) else [value]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                _append_fact(
                    verb=str(entry.get("what_did_you_build", "")),
                    what=str(entry.get("what_did_you_build", "")),
                    tool=str(entry.get("tools_used") or project_tool or ""),
                    metric=str(entry.get("metric", "")),
                    outcome=str(entry.get("how_it_works")
                                or project_outcome or ""),
                    action=str(entry.get("what_did_you_build", "")),
                )

    return [fact for fact in facts if fact.get("what")]


def _select_closest_context_fact(bullet_text: str, fact_pool: list[dict]) -> dict | None:
    if not fact_pool:
        return None

    bullet_tokens = _tokenize_text(bullet_text)
    best = None
    best_score = -1
    for fact in fact_pool:
        fact_text = " ".join([
            fact.get("what", ""),
            fact.get("tool", ""),
            fact.get("metric", ""),
            fact.get("outcome", ""),
            fact.get("action", ""),
        ])
        fact_tokens = _tokenize_text(fact_text)
        overlap = len(bullet_tokens & fact_tokens)
        if overlap > best_score:
            best_score = overlap
            best = fact
    return best


def _clean_sentence_fragment(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip())
    return text.strip(" .;,")


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


def _render_deterministic_template_bullet(fact: dict) -> str | None:
    if not fact:
        return None

    verb = _clean_sentence_fragment(
        fact.get("verb") or fact.get("action") or "Built"
    )
    what = _clean_sentence_fragment(fact.get("what", ""))
    tool = _clean_sentence_fragment(fact.get("tool", ""))
    metric = _clean_sentence_fragment(fact.get("metric", ""))
    outcome = _clean_sentence_fragment(fact.get("outcome", ""))
    action = _clean_sentence_fragment(fact.get("action", ""))

    if not what:
        return None

    # Keep leading article lowercase when {what} is inserted after verbs like "Built".
    what = re.sub(r"^(A|An|The)\b", lambda m: m.group(1).lower(), what)

    selected = None
    if what and tool and metric:
        selected = BULLET_TEMPLATES[0]
    elif what and tool and outcome:
        selected = BULLET_TEMPLATES[1]
    elif what and outcome and metric:
        selected = BULLET_TEMPLATES[2]
    elif what and tool and metric and action:
        selected = BULLET_TEMPLATES[3]
    elif what and tool and outcome:
        selected = BULLET_TEMPLATES[4]
    else:
        selected = "{verb} {what}."

    fill_values = {
        "verb": verb,
        "what": what,
        "tool": tool or "core technologies",
        "metric": metric or "measurable improvements",
        "outcome": outcome or "deliver key outcomes",
        "action": action.lower() if action else "building",
    }

    rendered = selected.format(**fill_values)

    # Fix article + capital pattern introduced by context phrases, e.g. "Built A" -> "Built a".
    rendered = re.sub(
        r"\b(a|an|the)\s+([A-Z])",
        lambda m: m.group(1) + " " + m.group(2).lower(),
        rendered,
    )

    # Replace semicolon-joined adverb clauses with sentence boundaries.
    rendered = re.sub(
        r";\s+([A-Z][a-z]+ly\s)",
        lambda m: ". " + m.group(1),
        rendered,
    )

    # Replace other sentence-like semicolon joins, preserving semicolons only for metric-style fragments.
    rendered = re.sub(
        r";\s+([A-Z][a-z]+\b)",
        lambda m: ". " + m.group(1),
        rendered,
    )

    rendered = _clean_sentence_fragment(rendered)
    rendered = _trim_visible_text_to_limit(
        rendered, _VALIDATOR_BULLET_MAX_VISIBLE_CHARS
    )
    if not rendered.endswith("."):
        rendered += "."
    return _escape_latex_inline(rendered)


def _validate_single_bullet_payload(payload: str, context_bank: dict) -> list[str]:
    warnings = []
    visible = _visible_text_from_latex(payload)
    lowered_visible = visible.lower()

    if _VALIDATOR_PLACEHOLDER_PATTERN.search(payload):
        warnings.append("[placeholder]")

    if _VALIDATOR_WEAK_OWNERSHIP_PATTERN.search(lowered_visible):
        warnings.append("[ownership]")

    first_word = _extract_first_word_for_action_check(visible)
    if first_word and first_word not in _VALIDATOR_ACTION_VERBS:
        warnings.append("[action_verb]")

    allowed_numbers = _collect_context_bank_numbers(context_bank)
    bullet_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", visible))
    if any(n not in allowed_numbers for n in bullet_numbers):
        warnings.append("[numbers]")

    allowed_tools = {
        _canonicalize_tool_term(tool)
        for tool in _collect_context_bank_tool_terms(context_bank)
    }
    candidates = set(allowed_tools)
    candidates.update({_canonicalize_tool_term(tool)
                      for tool in _VALIDATOR_COMMON_TOOL_TERMS})
    mentioned_tools = _find_tool_mentions(visible, candidates)
    if any(_canonicalize_tool_term(tool) not in allowed_tools for tool in mentioned_tools):
        warnings.append("[tools]")

    if len(visible) > _VALIDATOR_BULLET_MAX_VISIBLE_CHARS:
        warnings.append("[length]")

    return warnings


def _rewrite_weak_project_bullets_deterministically(
    tex_string: str,
    base_resume_tex: str,
    context_bank: dict,
) -> tuple[str, list[dict]]:
    """Phase 2: rewrite weak-start project bullets via deterministic templates."""
    proj_body = _extract_projects_body(tex_string)
    base_proj_body = _extract_projects_body(base_resume_tex)
    if not proj_body or not base_proj_body:
        return tex_string, []

    body_start, body_end, body = proj_body
    _, _, base_body = base_proj_body

    spans = _extract_bitem_payload_spans(body)
    base_spans = _extract_bitem_payload_spans(base_body)
    fact_pool = _build_context_fact_pool(context_bank)

    replacements = []
    fallback_events = []
    for idx, (start, end, payload) in enumerate(spans):
        visible = _visible_text_from_latex(payload)
        first_word = _extract_first_word_for_action_check(visible)
        should_rewrite = (
            first_word in WEAK_STARTERS
            or first_word not in ACTION_VERB_ALLOWLIST
        )
        if not should_rewrite:
            continue

        fallback_payload = payload
        if idx < len(base_spans):
            fallback_payload = base_spans[idx][2]

        matched_fact = _select_closest_context_fact(visible, fact_pool)
        rewritten_payload = _render_deterministic_template_bullet(matched_fact)
        if not rewritten_payload:
            replacements.append((start, end, fallback_payload))
            fallback_events.append({
                "bullet_index": idx + 1,
                "reason": "template_unavailable",
            })
            continue

        rewrite_warnings = _validate_single_bullet_payload(
            rewritten_payload, context_bank
        )
        if rewrite_warnings:
            replacements.append((start, end, fallback_payload))
            fallback_events.append({
                "bullet_index": idx + 1,
                "reason": "validator_failed",
                "warnings": rewrite_warnings,
            })
            continue

        replacements.append((start, end, rewritten_payload))

    if not replacements:
        return tex_string, fallback_events

    updated_body = body
    for start, end, replacement in sorted(replacements, key=lambda x: x[0], reverse=True):
        updated_body = updated_body[:start] + replacement + updated_body[end:]

    return tex_string[:body_start] + updated_body + tex_string[body_end:], fallback_events


def _validate_generated_resume_artifacts(output_dir: Path, context_bank: dict) -> list[str]:
    """Warn-only validator for generated resume artifacts. Does not block output."""
    warnings = []
    tex_path = output_dir / "resume.tex"

    if not tex_path.exists():
        return ["[validation] resume.tex missing; skipped bullet validators"]

    tex_content = tex_path.read_text(encoding="utf-8")
    bullets = _extract_bitem_payloads(tex_content)
    allowed_numbers = _collect_context_bank_numbers(context_bank)
    allowed_tools = {
        _canonicalize_tool_term(tool)
        for tool in _collect_context_bank_tool_terms(context_bank)
    }
    tool_candidates = {
        _canonicalize_tool_term(tool) for tool in allowed_tools
    }
    tool_candidates.update(
        {_canonicalize_tool_term(tool)
            for tool in _VALIDATOR_COMMON_TOOL_TERMS}
    )

    for idx, bullet in enumerate(bullets, start=1):
        visible = _visible_text_from_latex(bullet)
        lowered_visible = visible.lower()

        if _VALIDATOR_PLACEHOLDER_PATTERN.search(bullet):
            warnings.append(
                f"[placeholder] bullet {idx}: found template placeholder [your stack]"
            )

        if _VALIDATOR_WEAK_OWNERSHIP_PATTERN.search(lowered_visible):
            warnings.append(
                f"[ownership] bullet {idx}: weak ownership language detected"
            )

        first_word = _extract_first_word_for_action_check(visible)
        if first_word and first_word not in _VALIDATOR_ACTION_VERBS:
            warnings.append(
                f"[action_verb] bullet {idx}: first action word '{first_word}' is not allowed"
            )

        bullet_numbers = set(re.findall(r"\b\d+(?:\.\d+)?\b", visible))
        unknown_numbers = sorted(
            n for n in bullet_numbers if n not in allowed_numbers)
        if unknown_numbers:
            warnings.append(
                f"[numbers] bullet {idx}: numbers not present in context_bank: {', '.join(unknown_numbers)}"
            )

        mentioned_tools = _find_tool_mentions(visible, tool_candidates)
        unknown_tools = sorted(
            _canonicalize_tool_term(tool)
            for tool in mentioned_tools
            if _canonicalize_tool_term(tool) not in allowed_tools
        )
        if unknown_tools:
            warnings.append(
                f"[tools] bullet {idx}: tool(s) not present in context_bank: {', '.join(unknown_tools)}"
            )

        if len(visible) > _VALIDATOR_BULLET_MAX_VISIBLE_CHARS:
            warnings.append(
                f"[length] bullet {idx}: visible length {len(visible)} exceeds {_VALIDATOR_BULLET_MAX_VISIBLE_CHARS}"
            )

    pdf_files = list(output_dir.glob("*.pdf"))
    if not pdf_files:
        warnings.append("[pdf] generated PDF missing")
    else:
        try:
            with open(pdf_files[0], "rb") as f:
                page_count = len(pypdf.PdfReader(f).pages)
            if page_count != 1:
                warnings.append(f"[pdf] expected 1 page, found {page_count}")
        except Exception as exc:
            warnings.append(f"[pdf] failed to read generated PDF: {exc}")

    return warnings


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


def load_references() -> dict:
    """
    Loads core reference files (Base Resume LaTeX and Context Bank TOML).

    Returns:
        dict: Contains 'base_resume_tex' string and 'context_bank' dictionary.

    Raises:
        FileNotFoundError: If the base resume file is missing.
    """
    import tomllib  # Ensure tomllib is available if not globally imported
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
