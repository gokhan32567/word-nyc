# Working on Word NYC

- Any push that changes `scraper/**`, `sponsored.json` or `.github/workflows/update-events.yml` reruns the full lineup workflow (about $0.14 in AI costs). Batch small changes. For page-only tweaks (e.g. `scraper/pages.py`, `scraper/venue_notes.json`, `scraper/areas.py`), commit with `[skip ci]` in the message; the next 5 AM run rebuilds the pages.
- Venue outreach and email campaigns are handled in a separate chat. Don't email venues from here. Outreach emails link each venue to `https://word-nyc.com/badge/#<venue-slug>`.
- SEO pages and their sources are described in `SEO_CHANGES.md`.
