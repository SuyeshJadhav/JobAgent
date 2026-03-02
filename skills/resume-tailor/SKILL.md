---
name: resume-tailor
description: >
  Rewrites the candidate's LaTeX resume bullet points to mirror keywords and priorities from a specific JD.
  Use this when the user says "tailor my resume", "edit resume for this job", or after a job is shortlisted.
  Always reads base_resume.tex and never fabricates skills or experience not present there.
  Compiles LaTeX to PDF as final output.
---

# Resume Tailor Skill

Takes a JD and surgically edits the LaTeX resume to maximize keyword alignment.
Think of it like a chameleon — same experience, reframed to match what the JD is looking for.
Only edits text between comment markers — never touches LaTeX formatting/structure.

---

## Inputs
- JD text (from DB or pasted directly)
- `references/base_resume.tex` — master LaTeX resume (structure only)
- `references/context_bank.toml` — raw project notes with real numbers ← PRIMARY SOURCE
- `references/candidate_profile.md` — tone/style guide

## Source Priority Rule
```
context_bank.toml  → real numbers, decisions, what was hard (USE THIS FIRST)
base_resume.tex    → bullet structure and ordering
voice_samples      → match candidate's natural phrasing rhythm
JD keywords        → which words to surface, what verbs to use
```
Never invent a number. If context_bank has no metric for a bullet, use
scale or process language instead ("across 50k daily requests", "handling 8 PDF layouts").

## Human-Sounding Bullet Formula (from research)
Good bullets follow: ACTION VERB + WHAT + HOW/TOOL + RESULT/SCALE

❌ Bad (generic AI):  "Leveraged LLM technologies to optimize pipeline performance"
✅ Good (specific):   "Built RAG pipeline using LangChain + FAISS, cutting query latency from 5 min to 30 sec across 50k daily requests"

Key signals that a bullet sounds human:
- Mentions a specific tool choice AND why (e.g. "used LoRA to fit within GPU budget")
- Has a before/after ("from X to Y") rather than just "improved by X%"
- Includes what was hard or a tradeoff (shows real ownership)
- Varies verb and sentence structure — not every bullet starts with "Built"
- Could NOT be copy-pasted onto someone else's resume

## LaTeX Comment Markers (required in base_resume.tex)

Your `.tex` file must have these markers so the agent edits safely:

```latex
%% BEGIN SUMMARY %%
\item Your summary line here
%% END SUMMARY %%

%% BEGIN EXPERIENCE: CompanyName %%
\item Built an LLM pipeline using LangChain...
\item Deployed ML models to production REST APIs...
%% END EXPERIENCE: CompanyName %%

%% BEGIN PROJECTS %%
\item AI Job Agent — automated pipeline using Python and OpenAI API
%% END PROJECTS %%

%% BEGIN SKILLS %%
Python, LangChain, PyTorch, RAG, NLP
%% END SKILLS %%
```

The agent reads ONLY between these markers. Everything else in the `.tex` is untouched.

---

## Steps

1. **Extract JD keywords** — LLM pulls:
   - Required tools & skills
   - Role-specific action verbs ("deploy", "fine-tune", "design", "scale")
   - Seniority signals, domain focus

2. **Map keywords → resume sections** — find which bullets are most relevant to JD

3. **Rewrite bullets (text only)** — LLM rewrites text between markers:
   - Swap verbs to match JD language
   - Surface JD keywords in first bullet of each section
   - Never add skills/tools not already in the file

4. **Write tailored `.tex`** — copy `base_resume.tex`, replace only marked sections

5. **Compile to PDF**:
```bash
pdflatex tailored_resume_Google_AIEngineer.tex
```

6. **Output** → `tailored_resume_{Company}_{Role}.pdf`

---

## LLM Prompt Pattern

```
You are editing LaTeX resume bullet points for a specific job.

JD KEYWORDS: {keywords}
CURRENT BULLETS (plain text, extracted from between markers):
{bullet text only — no LaTeX commands}

Rules:
- Rewrite bullets to use JD verbs and keywords
- Keep each bullet under 2 lines
- Never add tools or experience not in the original
- Never modify LaTeX commands, only the text content
- Return ONLY the rewritten bullet text lines, one per line
```

---

## Output Files
```
outputs/
└── resumes/
    ├── tailored_resume_Google_AIEngineer.tex
    ├── tailored_resume_Google_AIEngineer.pdf   ← upload this
    └── ...
```

## Script
Run: `scripts/resume_tailor.py --job_id <id>`

## Compilation Requirements
- `pdflatex` must be installed (`apt install texlive-full` or use Overleaf export)
- Alternative: use `latexmk` for cleaner compilation

## Rules
- **Never edit LaTeX commands** — only text between `\item` and end of line
- **Never fabricate** skills or tools not in `base_resume.tex`
- Always compile and verify PDF renders before saving output
- One unique `.tex` + `.pdf` per job — never reuse
- Store PDF output path in DB under the job's row
