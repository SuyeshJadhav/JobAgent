# JobAgent System Design

JobAgent is built with a **Philosophy of Speed and Privacy**. It avoids heavy infrastructure, relying on localized, ephemeral storage and local intelligence.

## 🏛️ Core Philosophies

### 1. Filesystem-First State
Instead of a traditional remote database, JobAgent uses **SQLite** (`backend/tracked_jobs.db`) for structured tracking and the **Local Filesystem** for large artifacts (JDs, Resumes).
- **Transparency**: You can open the DB in any SQLite viewer or export to Excel.
- **Portability**: All your data lives in your project folder. No cloud login required.

### 2. The Shredder (Strict Ephemeral Storage)
JobAgent implements a "Shredder" protocol found in `backend/routers/sniper.py`. 
- When a job is marked as **Applied**, the system automatically deletes the generated `.tex` files, PDF builds, and temporary JD JSONs.
- **Why?** To keep the storage footprint lean and ensure that sensitive, tailored data doesn't accumulate unnecessarily. Only the high-level metadata remains in the SQLite DB for your application history.

### 3. Shrink-to-Fit LaTeX Logic
Generating a perfect 1-page resume programmatically is hard. JobAgent handles this with a 2-pass recursive compilation strategy in `backend/services/resume_tailor.py`:
- **Pass 1 (Normal)**: Attempt to compile with the tailored LLM content.
- **Pass 2 (Trim)**: If the PDF is >1 page, the system automatically trims secondary bullet points and reduces LaTeX vertical spacing (`itemsep`) to squeeze the content onto a single page without human intervention.

## 🛠️ Components

### The Sniper Pipeline
The "Sniper" is the most advanced part of the project. It works through a coordinated effort:
1. **Detection**: `extension/content.js` uses a MutationObserver to find textareas and map them to their corresponding "Question" labels using a hierarchy of DOM heuristics.
2. **Context Assembly**: The backend (`backend/routers/sniper.py`) pulls from your `profile/*.md` files and the scraped JD stored in `outputs/`.
3. **LLM Synthesis**: The LLM generates a 2-3 sentence answer tailored *specifically* to that company's mission and your history.
4. **React-Safe Injection**: Answers are injected via simulated browser events to ensure they are picked up by modern frameworks like React or Vue without being cleared by state management.

### The FAM (Floating Action Menu)
The Extension UI is a **Neo-Brutalist** Floating Action Menu.
- **Status Persistence**: It tracks whether you are in a "Tracked", "Tailored", or "Applied" state based on backend truth.
- **Action Chaining**: It guides you through the funnel: `Track` -> `Tailor` -> `Inject` -> `Applied`.
