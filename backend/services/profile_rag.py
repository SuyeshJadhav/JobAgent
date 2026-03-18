import json as json_mod
import re
import uuid
from pathlib import Path

from backend.services.llm_client import get_llm_client, get_model_name
from backend.utils.profile_loader import load_profile_file

try:
    import chromadb
    from chromadb.utils import embedding_functions
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False

PROFILE_DIR = Path(__file__).parent.parent.parent / "profile"
VECTOR_CACHE_DIR = PROFILE_DIR / "vector_cache"

# Initialize ChromaDB persistent client if available
chroma_client = None
cache_collection = None

if CHROMA_AVAILABLE:
    VECTOR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(VECTOR_CACHE_DIR))
    # Use default MiniLM-L6-v2 embedding function locally
    emb_fn = embedding_functions.DefaultEmbeddingFunction()

    # Get or create the cache collection
    cache_collection = chroma_client.get_or_create_collection(
        name="autofill_cache",
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"}
    )


def _normalize_key(field_name: str) -> str:
    """Normalize a field name for fast path lookups."""
    return field_name.strip().lower()


def _build_fast_path_map() -> dict[str, str]:
    """
    Build a keyword→answer lookup from all profile files.
    Parsed at call time so values stay in sync with profile data.
    """
    profile_data = {}

    # Load all profile files and extract all KEY: VALUE pairs
    for filename in ["personal_info.md", "visa.md", "education.md"]:
        content = load_profile_file(filename)
        # Matches both "Key: Value" and "KEY_NAME: Value"
        matches = re.findall(r"^([\w\s_]+):\s*(.*)$", content, re.MULTILINE)
        for k, v in matches:
            key = k.strip().lower().replace("_", " ")
            profile_data[key] = v.strip()

    # Derived fields
    first = profile_data.get(
        "first name") or profile_data.get("first name") or ""
    middle = profile_data.get("middle name") or ""
    last = profile_data.get("last name") or profile_data.get("last name") or ""
    full = profile_data.get(
        "full name") or f"{first} {middle} {last}".replace("  ", " ").strip()

    # Base map
    fast_map = {
        "first name":       first,
        "middle name":      middle,
        "last name":        last,
        "full name":        full,
        "email":            profile_data.get("email", ""),
        "phone":            profile_data.get("phone number") or profile_data.get("phone", ""),
        "phone number":     profile_data.get("phone number") or profile_data.get("phone", ""),
        "linkedin":         profile_data.get("linkedin url") or profile_data.get("linkedin", ""),
        "github":           profile_data.get("github url") or profile_data.get("github", ""),
        "portfolio":        profile_data.get("portfolio url") or profile_data.get("portfolio", ""),
        "address":          profile_data.get("full address") or profile_data.get("address", ""),
        "city":             profile_data.get("city", ""),
        "state":            profile_data.get("state", ""),
        "zip":              profile_data.get("postal code") or profile_data.get("zip", ""),
        "postal code":      profile_data.get("postal code") or profile_data.get("zip", ""),
        "work authorization": profile_data.get("work authorization status") or profile_data.get("work authorization", ""),
        "visa":             profile_data.get("visa sponsorship") or profile_data.get("visa", ""),
        "sponsor":          profile_data.get("visa sponsorship") or profile_data.get("visa", ""),
    }

    # Demographics / Fallbacks
    fast_map.update({
        "gender":           "Decline to self-identify",
        "race":             "Decline to self-identify",
        "ethnicity":        "Decline to self-identify",
        "veteran":          "I am not a protected veteran",
        "disability":       "I don't wish to answer",
        "handicap":         "I don't wish to answer",
    })

    return {k: v for k, v in fast_map.items() if v}


def _match_fast_path(field_name: str, fast_map: dict[str, str]) -> str | None:
    """
    Check if a field name matches any fast-path keyword.
    Returns the answer if matched, None otherwise.
    """
    field_lower = field_name.lower()

    # Priority 1: Exact match (normalized)
    norm_field = field_lower.replace("_", " ").replace("-", " ")
    if norm_field in fast_map:
        return fast_map[norm_field]

    # Priority 2: Keyword containment (longest keyword first)
    sorted_keys = sorted(fast_map.keys(), key=len, reverse=True)
    for keyword in sorted_keys:
        if keyword in norm_field:
            return fast_map[keyword]

    return None


def _handle_standard_fields(fields: list[str]) -> tuple[dict[str, str], list[str]]:
    """
    Handles fast path keyword matching and ChromaDB vector cache semantic lookups.
    Returns a tuple of (resolved_fields_dict, unresolved_llm_fields_list).
    """
    fast_map = _build_fast_path_map()
    results = {}
    llm_fields = []

    for field in fields:
        norm = _normalize_key(field)

        # Tier 1: Fast path keyword match (High priority + File-synced)
        fast_answer = _match_fast_path(field, fast_map)
        if fast_answer is not None:
            results[field] = fast_answer

            # Synchronize this value to Vector Cache (Tier 2) to prevent stale hits
            if cache_collection is not None:
                try:
                    # Use a deterministic ID based on normalized field name to overwrite old cached values
                    deterministic_id = f"fp_{norm.replace(' ', '_')}"
                    cache_collection.upsert(
                        ids=[deterministic_id],
                        documents=[field],
                        metadatas=[
                            {"answer": fast_answer, "source": "fast_path"}]
                    )
                except Exception:
                    pass
            continue

        # Tier 2: Vector Cache lookup (Semantic Fallback)
        cached_answer = None
        if cache_collection is not None:
            try:
                qr = cache_collection.query(
                    query_texts=[field],
                    n_results=1
                )
                if qr['distances'] and qr['distances'][0] and qr['distances'][0][0] < 0.4:
                    if qr['metadatas'] and qr['metadatas'][0]:
                        cached_answer = qr['metadatas'][0][0].get('answer')
                        print(
                            f"[CACHE HIT] '{field}' matched '{qr['documents'][0][0]}' (dist: {qr['distances'][0][0]:.3f})")
            except Exception as e:
                print(f"[WARN] Chroma DB query failed for '{field}': {e}")

        if cached_answer is not None:
            results[field] = cached_answer
            continue

        # Tier 3: Needs LLM (Slow Path)
        llm_fields.append(field)

    return results, llm_fields


def _generate_llm_answers(llm_fields: list[str], job_url: str = "", company: str = "") -> dict[str, str]:
    """
    Uses an LLM to generate answers for complex or essay fields that couldn't be resolved via fast path or cache.
    Saves non-company-specific answers back to the ChromaDB cache.
    """
    if not llm_fields:
        return {}

    results = {}
    company_lower = (company or "").strip().lower()

    profile_sections = []
    for filename in ["personal_info.md", "visa.md", "work_experience.md",
                     "projects.md", "education.md", "skills.md", "essay_bank.md"]:
        content = load_profile_file(filename)
        if content.strip():
            profile_sections.append(f"--- {filename} ---\n{content}")

    full_profile = "\n\n".join(profile_sections)
    fields_json = json_mod.dumps(llm_fields, indent=2)

    system_prompt = (
        "You are an expert job application autofill assistant. "
        "I will provide my profile context and a list of form fields. "
        "Return ONLY a valid JSON object where the keys are the EXACT "
        "field names provided, and the values are the best answers based "
        "on my profile.\n\n"
        "Rules:\n"
        "- For simple fields (name, email, URL): return the exact value.\n"
        "- For essay/open-ended fields: provide a concise answer (max 150 words).\n"
        "- If a field cannot be answered from the profile, use: \"Not specified in profile.\"\n"
        "- Do NOT invent information.\n"
        "- Return ONLY the JSON object — no markdown fences, no explanation."
    )

    user_prompt = (
        f"Company: {company}\n"
        f"Job URL: {job_url}\n\n"
        f"=== MY PROFILE ===\n{full_profile}\n\n"
        f"=== FORM FIELDS TO FILL ===\n{fields_json}\n\n"
        "Return the JSON object now."
    )

    try:
        client = get_llm_client()
        model = get_model_name()

        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        raw = resp.choices[0].message.content.strip()

        llm_answers = None

        # Try direct JSON parse
        try:
            llm_answers = json_mod.loads(raw)
        except json_mod.JSONDecodeError:
            pass

        # Fallback: extract JSON from markdown code fences
        if llm_answers is None:
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
            if json_match:
                try:
                    llm_answers = json_mod.loads(json_match.group(1))
                except json_mod.JSONDecodeError:
                    pass

        # Fallback: find first { ... } block
        if llm_answers is None:
            brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if brace_match:
                try:
                    llm_answers = json_mod.loads(brace_match.group(0))
                except json_mod.JSONDecodeError:
                    pass

        if llm_answers and isinstance(llm_answers, dict):
            results.update(llm_answers)

            # ── Learn: save non-company-specific answers to cache ──────
            new_docs = []
            new_metadatas = []
            new_ids = []

            for field_name, answer in llm_answers.items():
                if answer == "Not specified in profile.":
                    continue
                # Skip company-specific questions (e.g. "Why Google?")
                if company_lower and company_lower in field_name.lower():
                    print(f"[CACHE] Skipping company-specific: '{field_name}'")
                    continue

                new_docs.append(field_name)
                new_metadatas.append({"answer": answer, "source": "llm"})
                new_ids.append(str(uuid.uuid4()))

            # Add to Chroma
            if cache_collection is not None and new_docs:
                try:
                    cache_collection.add(
                        documents=new_docs,
                        metadatas=new_metadatas,
                        ids=new_ids
                    )
                    print(
                        f"[CACHE] Added {len(new_docs)} new answers to vector db")
                except Exception as e:
                    print(f"[WARN] Failed to write to vector db: {e}")

        else:
            print(f"[WARN] Could not parse batch LLM response: {raw[:200]}")
            for f in llm_fields:
                results[f] = "Not specified in profile."

    except Exception as e:
        print(f"[ERROR] Batch fill failed: {e}")
        for f in llm_fields:
            results[f] = "Not specified in profile."

    return results


def batch_fill_fields(fields: list[str], job_url: str = "", company: str = "") -> dict[str, str]:
    """
    Traffic controller that orchestrates the field filling process.
    1. Delegates standard fields to fast path / cache.
    2. Delegates complex fields to the LLM.
    3. Merges and returns the complete result dictionary conforming to the API contract.
    """
    # Step 1: Handle standard fields via fast path and vector cache
    results, llm_fields = _handle_standard_fields(fields)

    # Calculate stats
    fast_map = _build_fast_path_map()
    fast_path_count = sum(
        1 for f in fields if f in results and _match_fast_path(f, fast_map) is not None)
    cache_count = len(results) - fast_path_count
    print(
        f"[FILL] Fast Path: {fast_path_count} | Cache Hits: {cache_count} | LLM: {len(llm_fields)}")

    # Step 2: Handle remaining fields via LLM
    if llm_fields:
        llm_results = _generate_llm_answers(llm_fields, job_url, company)
        results.update(llm_results)

    # Step 3: Return the merged dictionary
    return results
