import re

from backend.services.bullet_validator import (
    _validate_single_bullet_payload,
    _extract_first_word_for_action_check,
    _VALIDATOR_BULLET_MAX_VISIBLE_CHARS,
)
from backend.utils.latex_utils import (
    _extract_bitem_payload_spans,
    _visible_text_from_latex,
    _escape_latex_inline,
    _trim_visible_text_to_limit,
)

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

METRIC_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(ms|sec|s|min|hrs?|%|x|X|"
    r"tokens?/sec|texts?/sec|req/sec|"
    r"queries/sec|users?|records?|"
    r"endpoints?|tools?|stages?|"
    r"components?|k|K|M|GB|MB)",
    flags=re.IGNORECASE,
)


def _extract_metric(text: str) -> str:
    """Extract the first compact numeric metric token from free-form text."""
    if not text:
        return ""
    matches = METRIC_PATTERN.findall(text)
    if not matches:
        return ""
    number, unit = matches[0]
    return f"{number}{unit}"


def _extract_projects_body(tex_string: str) -> tuple[int, int, str] | None:
    match = re.search(
        r"\\section\{Projects\}(?P<body>.*?)(?=\\section\{Experience\})",
        tex_string,
        flags=re.DOTALL,
    )
    if not match:
        return None
    return match.start("body"), match.end("body"), match.group("body")


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
