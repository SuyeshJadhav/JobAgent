---
name: scorer
description: >
  Scores each job listing for role fit — not resume match. Use this after scout finds jobs.
  Trigger when user asks "is this a good fit", "score this JD", or after scout runs.
  Filters out mismatched roles before resume tailoring begins.
---

# Scorer Skill

Scores jobs 1–10 based on how well they match the candidate's **target role preferences** —
not their resume. Think of this as a job filter, not a resume matcher.

---

## Scoring Criteria

| Factor | What to check |
|---|---|
| Role title match | Is it AI/ML/LLM related? |
| Seniority level | Intern / new grad / junior? Or requires 5+ yrs? |
| Location | Remote or US? |
| Red flags | Unrelated domain, unrealistic requirements |
| Upside signals | Mentions LLMs, agents, Python, RAG |

## Score Meaning
- **8–10**: Strong match → send to resume tailor
- **6–7**: Partial match → send to resume tailor with note
- **1–5**: Poor match → mark as `skipped`, do not tailor

## LLM Prompt Pattern

```
You are filtering jobs for a candidate.

CANDIDATE PREFERENCES:
{load from candidate_profile.md}

JOB:
Title: {title}
Company: {company}
Description: {jd_snippet}

Score 1-10 based on role fit (NOT resume match).
Reply ONLY as JSON: {"score": <n>, "reason": "<one sentence>"}
```

## Steps

1. For each job with status = `found` in DB
2. Send JD + candidate preferences to LLM (gpt-4o-mini)
3. Parse score + reason
4. Update DB: set `score`, `reason`
5. If score ≥ 6 → set status = `shortlisted`
6. If score < 6 → set status = `skipped`

## Threshold
Default: `SCORE_THRESHOLD = 6` (configurable in candidate_profile.md)

## API Integration
Run: `backend/services/scorer.py` or trigger through `POST /api/scout/run`

## Rules
- Score based on role fit only — ignore resume
- Never skip scoring — every new job must be scored
- Always log reason alongside score
