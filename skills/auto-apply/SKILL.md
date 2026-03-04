---
name: auto-apply
description: >
  Automates job application submission using Playwright on LinkedIn, Indeed, and Handshake.
  Use when the user says "apply to shortlisted jobs", "run auto-apply", or "submit applications".
  Always asks for user confirmation before submitting. Never applies without approval.
---

# Auto-Apply Skill

Uses Playwright to fill and submit job applications automatically.
Like a robot intern — clicks buttons, fills forms, uploads files.

---

## Pre-conditions (must all be true before applying)
- [ ] Job has status = `shortlisted` in DB
- [ ] Tailored resume `.docx` exists for this job
- [ ] Cover letter exists for this job
- [ ] User has confirmed: "yes, apply to these"

## Supported Portals

| Portal | Method | Notes |
|---|---|---|
| LinkedIn | Easy Apply (in-app) | Most reliable, no redirect |
| Indeed | Indeed Apply | Medium reliability |
| Handshake | Form-based | Needs session login |
| Company sites | Case-by-case | Manual fallback |

## Steps

1. Load shortlisted jobs from DB (status = `shortlisted`, resume + cover letter ready)
2. Show list to user → **ask for confirmation before proceeding**
3. For each confirmed job:
   - Open apply URL in Playwright browser
   - Detect portal type (LinkedIn / Indeed / Handshake / other)
   - Fill standard fields: name, email, phone, location
   - Upload tailored resume `.docx`
   - Paste cover letter text if field available
   - Submit form
   - Capture confirmation (screenshot or confirmation text)
4. Update DB: status = `applied`, applied_at = now

## Failure Handling

| Failure | Action |
|---|---|
| CAPTCHA detected | Pause, notify user, skip job |
| Form structure unknown | Screenshot + notify user, mark as `manual_needed` |
| Login required | Use stored session cookies (see setup) |
| Application limit hit | Stop, notify user |

## Rate Limiting
- Wait 30–60 seconds between applications
- Max 10 applications per run (safety limit)
- Rotate between portals if possible

## Extention Integration
Trigger Autofill from Chrome Extension which posts to `POST /api/profile/fill`

## Setup Required
- LinkedIn session cookies saved to `config/linkedin_cookies.json`
- Indeed session saved to `config/indeed_cookies.json`
- Headless mode: off by default (so user can monitor)

## Rules
- **NEVER apply without user confirmation**
- Always screenshot the confirmation page
- Log every attempt — success or failure
- Mark failed applications as `failed` not `applied`
