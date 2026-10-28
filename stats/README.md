# Word NYC stats

Cookie-free daily totals for sponsor reports (and for Impact): app/map opens, daily users, noon-push
deliveries and opens, ticket-link taps per venue, sponsored views and taps, venue followers.

- `worker.js`: Cloudflare Worker (free plan) with a D1 database (`schema.sql`).
- Deployed by **Actions → Deploy stats worker** (`.github/workflows/stats-worker.yml`). The first run creates the
  database, sets the `STATS_KEY` secret on the worker, deploys, and writes the worker's address into `wn.js`
  (`STATS_URL`), which switches counting on for the site and the app.
- Report: `https://word-nyc.com/app-stats.html#key=<STATS_KEY>` (not linked, not indexed). Pick a month, then
  copy a venue's row or download the JSON for a sponsor.

What is sent from a phone or browser: `{ m: metric, p: "app" | "web", k: venue slug or source, f: first open today }`.
No cookie, ID, advertising identifier or IP address is stored. Unique users are counted with an "already opened
today" flag kept on the device, so there are daily users but no monthly unique users.

Metrics: `open` (k = push / resume / source), `tix` ticket tap, `stix` ticket tap on a sponsored show,
`spv` sponsored show listed, `spt` sponsored show opened, `fav` / `unfav` follow / unfollow, `share`
(k = show / map / story).
