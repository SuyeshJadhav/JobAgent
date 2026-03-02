---
name: job-application-agent
description: >
  Full end-to-end job application automation pipeline for an MCS student with AI/ML background.
  Use this skill whenever the user wants to find jobs, tailor a resume to a JD, write cover letters,
  auto-apply, or track applications. Trigger this skill for any request involving job search,
  resume editing, application automation, JD analysis, or career pipeline tasks.
  Each module also works standalone — trigger individual skills for partial tasks.
---

# Job Application Agent — Master Skill

You are an autonomous job application agent built for Suyesh Jadhav (MCS @ NC State).

---

## ⚠️ CRITICAL — READ BEFORE DOING ANYTHING

**Before writing ANY code or running ANY task, you MUST:**

1. Read THIS file completely first
2. Then read the relevant sub-skill SKILL.md from `skills/` folder
3. Then read `references/candidate_profile.md`

**Sub-skill SKILL.md files are located at:**
```
skills/scout/SKILL.md          ← read before building/running scout
skills/scorer/SKILL.md         ← read before building/running scorer
skills/resume-tailor/SKILL.md  ← read before building/running resume tailor
skills/cover-letter/SKILL.md   ← read before building/running cover letter
skills/auto-apply/SKILL.md     ← read before building/running auto-apply
skills/tracker/SKILL.md        ← read before building/running tracker
```

Each SKILL.md contains the exact inputs, outputs, logic, prompts, and rules for that module.
**Do not guess or assume — always read the skill file first.**

---

## Two Modes — Pipeline AND Standalone

This agent supports two usage modes. Every module must support both.

### Mode 1 — Full Pipeline
```
Target Roles (user-defined)
        ↓
[SKILL: scout]         → Find fresh jobs daily via JSearch API
        ↓
[SKILL: scorer]        → LLM filters by role fit (not resume match)
        ↓
[SKILL: resume-tailor] → Rewrite resume bullets to mirror JD keywords
        ↓
[SKILL: cover-letter]  → Generate targeted cover letter per JD
        ↓
[SKILL: auto-apply]    → Playwright automation on LinkedIn/Indeed/Handshake
        ↓
[SKILL: tracker]       → Log all applications to SQLite
```
Run with: `python pipeline.py --full`

### Mode 2 — Standalone (each module runs independently)
```
python scripts/scout_agent.py                      ← just find jobs
python scripts/resume_tailor.py --job_id 123       ← just tailor one resume
python scripts/cover_letter.py --job_id 123        ← just one cover letter
python scripts/auto_apply.py --job_id 123          ← just apply to one job
python scripts/tracker.py --show                   ← just show tracker
python scripts/interview_agent.py                  ← populate context bank
```

### Standalone Design Rule — Non-Negotiable
Every script MUST expose a `run()` function so pipeline.py can import it:
```python
# Every script must follow this pattern exactly:

def run(job_id=None, **kwargs):
    """Core logic here — works both standalone and when imported"""
    pass

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--job_id", type=str)
    args = parser.parse_args()
    run(job_id=args.job_id)
```

---

## Reference Files — Load Order

Always load in this order before executing any task:

```
1. skills/{module}/SKILL.md         ← task-specific instructions
2. references/candidate_profile.md  ← who this is for
3. references/context_bank.toml     ← real project notes + metrics
4. references/base_resume.tex       ← resume structure + markers
5. references/cover_letter_template.md ← tone/style (cover letter only)
```

---

## When to Use Each Skill

| User says... | Read this SKILL.md | Run this script |
|---|---|---|
| "find jobs", "scout today" | `skills/scout/SKILL.md` | `scout_agent.py` |
| "score this JD", "good fit?" | `skills/scorer/SKILL.md` | `scout_agent.py` (integrated) |
| "tailor my resume" | `skills/resume-tailor/SKILL.md` | `resume_tailor.py` |
| "write cover letter" | `skills/cover-letter/SKILL.md` | `cover_letter.py` |
| "apply to jobs" | `skills/auto-apply/SKILL.md` | `auto_apply.py` |
| "show applications" | `skills/tracker/SKILL.md` | `tracker.py` |
| "add project to context bank" | — | `interview_agent.py` |
| "run full pipeline" | All SKILL.md files | `pipeline.py --full` |
| "run from tailor onwards" | tailor + cover + apply + tracker | `pipeline.py --from tailor` |

---

## File Structure

```
job-application-agent/
├── SKILL.md                           ← you are here (read first)
├── references/
│   ├── candidate_profile.md           ← background, target roles, prefs
│   ├── base_resume.tex                ← LaTeX resume with %% markers %%
│   ├── custom-commands.tex            ← LaTeX custom commands
│   ├── context_bank.toml              ← raw project notes + real metrics
│   └── cover_letter_template.md       ← tone + style guide
├── skills/                            ← READ THESE BEFORE BUILDING
│   ├── scout/SKILL.md
│   ├── scorer/SKILL.md
│   ├── resume-tailor/SKILL.md
│   ├── cover-letter/SKILL.md
│   ├── auto-apply/SKILL.md
│   └── tracker/SKILL.md
├── scripts/                           ← built scripts go here
│   ├── scout_agent.py                 ✅ done
│   ├── interview_agent.py             ✅ done
│   ├── resume_tailor.py               ← build next
│   ├── cover_letter.py                ← after tailor
│   ├── auto_apply.py                  ← after cover letter
│   ├── tracker.py                     ← after auto_apply
│   └── pipeline.py                    ← build last
├── outputs/
│   ├── resumes/                       ← tailored .tex + .pdf per job
│   └── cover_letters/                 ← cover letters per job
└── scout_jobs.db                      ← SQLite database (single source of truth)
```

---

## Database — Single Source of Truth

All modules read/write to `scout_jobs.db`. Schema:
```sql
CREATE TABLE jobs (
  job_id            TEXT PRIMARY KEY,
  title             TEXT,
  company           TEXT,
  location          TEXT,
  apply_link        TEXT,
  description       TEXT,
  score             INTEGER,
  reason            TEXT,
  found_at          TEXT,
  applied_at        TEXT,
  status            TEXT,
  resume_path       TEXT,
  cover_letter_path TEXT,
  notes             TEXT,
  last_updated      TEXT
)
```

Status lifecycle:
```
found → shortlisted → resume_ready → cover_ready → applied
              ↘ skipped (score < 6)
                            ↘ failed / manual_needed
```

---

## Non-Negotiable Rules

1. **Read sub-skill SKILL.md before building any module** — no exceptions
2. **Every script supports both standalone + pipeline mode** via `run()` function
3. **Never fabricate** — only use content from `context_bank.toml` and `base_resume.tex`
4. **Always deduplicate** — check `job_id` in DB before any action
5. **Score first** — never tailor a resume for a job with score < 6
6. **Ask before applying** — always confirm with user before `auto_apply.py` runs
7. **One resume per job** — unique `.tex` + `.pdf` per `job_id`, never reuse
8. **Log everything** — every action updates `status` and `last_updated` in DB
9. **Compile and verify** — always check PDF renders before marking `resume_ready`
10. **LaTeX markers only** — resume tailor edits ONLY text between `%% BEGIN/END %%` markers