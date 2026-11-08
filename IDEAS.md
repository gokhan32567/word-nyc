# Ideas for later

Not scheduled. Recorded so any chat working on Word NYC can pick them up.

## Theatre, Broadway and similar shows (added Nov 8, 2026)
Apply the Word NYC approach (tonight's map, daily crawl, same AI reader and checks) to theatre:
Broadway, Off-Broadway, Off-Off-Broadway, dance, opera houses' non-music nights, comedy, cabaret.

Notes for when it starts:
- Decide: a new section/filter on word-nyc.com ("Theatre" next to the music genres) vs. a separate site.
- Theatre runs are long: most shows play 6-8 times a week for months, so a show list + weekly
  schedule (8 PM Tue-Sat, 2 PM Wed/Sat/Sun matinees...) matters more than daily calendars.
  The reader's multi-night-run support (`run_covers`, venue `sets`) already handles this pattern.
- Sources: Broadway League / IBDB-style schedules, Playbill, TodayTix/TKTS (rush and discount
  tickets are a strong "tonight" hook), venue sites; Ticketmaster already lists many Broadway houses.
- Ticket affiliates matter more here (Broadway tickets are expensive), so this pairs with
  the Ticketmaster/Impact reapplication.

## Other cities
Word DC (word-dc.com) and others: copy the engine, swap the city-specific parts (venue list,
neighborhoods, map center, branding, accounts). Write `docs/HANDBOOK.md` first so a new chat
can do it. Plan in the build chat, Nov 8, 2026.

## Open shared links in the iPhone app
Universal links (apple-app-site-association + Associated Domains) so word-nyc.com links open in the
app when installed. Needs a new app build and App Review; do with the next app update.
