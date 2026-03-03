# JobAgent API

## Backend setup

JobAgent uses a localized file-system tracking approach, eliminating the need for complex API integrations or external database hostings. We use a simple `.csv` file format which acts securely as the application's native state synchronization source.

When the application is launched and endpoints are hit for the first time, a database will be automatically created at the root directory of this project:

```text
tracked_jobs.csv
```

### Benefits of the Native CSV Sync:
1. **No Setup Required**: Simply boot the server and start letting the Python AI score applications.
2. **Offline Mode**: Easily read your history without an internet connection.
3. **Excel/Sheets Capabilities**: The file can natively simply be double-clicked to open directly into Excel. You can freely apply data-filters, insert graphs, format conditionally, or modify status statuses exactly like you normally would. The Python backend reads these edits dynamically parsing changes safely!

### Schema Definition:
- **job_id**: Internal tracker mapping to deduplicate jobs.
- **company**: Name of the company.
- **title**: Listing title.
- **status**: Defaults to `found`. Transitions smoothly to `shortlisted`, `applied`, `interviewing`, `rejected`, `offer`
- **score**: The LLM parsing score checking against your background profile match.
- **reason**: Why the LLM gave the score. 
- **apply_link**: The URL application route.
- **source**: `simplify`, `greenhouse`, `lever` 
- **location**: Location text 
- **found_at**: Discovered metric 
- **applied_date**: Stored time you moved to applied
- **resume_path**: Target compilation LaTeX location 
- **cover_letter_path**: Generation Location
- **notes**: Localized string injection buffer
- **last_updated**: Time parsing metric 
