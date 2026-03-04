---
name: cover-letter
description: >
  Generates a targeted cover letter for a specific job using the JD and candidate profile.
  Use when the user asks to write a cover letter, or after resume tailoring completes.
  Always sounds like the candidate — never generic. Reads tone guide from cover_letter_template.md.
---

# Cover Letter Skill

Generates a concise, targeted cover letter per job. Reads the JD + candidate profile
and writes something that sounds human — not like a template.

---

## Inputs
- JD text (from DB)
- `references/candidate_profile.md`
- `references/cover_letter_template.md` — tone/style instructions
- Tailored resume (for consistency)

## Structure (3 short paragraphs)

```
Para 1 — Hook:
  Why this role at this company specifically?
  Reference something real from the JD or company.

Para 2 — Value:
  What makes you a strong fit?
  Pick 2 most relevant experiences from tailored resume.
  Use JD language.

Para 3 — Close:
  Brief, confident close. No begging.
  One line CTA.
```

## LLM Prompt Pattern

```
Write a cover letter for this candidate applying to this job.

CANDIDATE: {candidate_profile}
JD SUMMARY: {jd_keywords + role + company}
TONE GUIDE: {cover_letter_template.md}

Rules:
- Max 250 words
- 3 paragraphs only
- Sound human, not corporate
- Reference something specific from the JD
- No generic phrases like "I am excited to apply"
- Do not repeat the resume — complement it

Return ONLY the cover letter text.
```

## Output Files
```
outputs/
└── cover_letters/
    ├── cover_letter_Google_AIEngineer.md
    └── ...
```

## API Integration
Endpoint: `POST /api/tailor/cover_letter` or run `backend/services/cover_letter.py`

## Rules
- Max 250 words
- No generic openers
- Always reference something specific from the JD
- Store output path in DB
