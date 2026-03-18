import json
import re
from pathlib import Path

import pypdf

from backend.utils.latex_utils import _extract_bitem_payloads, _visible_text_from_latex

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
