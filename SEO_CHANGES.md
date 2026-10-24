# SEO pass — October 2026

## Already in place (left as is)
- schema.org Event JSON-LD on the all-shows, genre and venue pages (MusicEvent/ComedyEvent/DanceEvent, offers, performers, fallback images)
- MusicVenue data on venue pages, canonical tags, sitemap.xml, robots.txt pointing at the sitemap
- Cloudflare Web Analytics on every page

## Added
- **Neighborhood pages** `/neighborhood/<area>/`: 20 neighborhoods (3+ venues each), plus Brooklyn and Queens. Each page has a stable intro, tonight's shows and the venue list. The ZIP→neighborhood map is in `scraper/areas.py`; fix a misplaced venue in `OVERRIDES` there.
- **Venue index** `/venues/`: every venue grouped by borough, with neighborhood chips. This is the internal-link hub.
- **Venue pages**:
  - A stable intro paragraph (hand-written for 15 jazz clubs in `scraper/venue_notes.json`, automatic for the rest).
  - A neighborhood link.
  - "Nearby tonight" links, so empty nights aren't dead ends.
  - A clearer title and description.
  - Geo coordinates added to the venue schema.
  - A badge invite.
- **Breadcrumbs** (visible trail plus BreadcrumbList schema) on venue, neighborhood and evergreen pages.
- **`/late-night-jazz/`**: jazz sets starting at 10 PM or later.
- **`/free-shows/`**: shows priced free or no cover.
- **`/guides/best-small-jazz-clubs-nyc/`**: 14 clubs, each with tonight's count and ItemList schema.
- **`/badge/`**: a venue picker that generates copy-paste HTML for `icons/badge.svg`. Links carry `utm_source=badge`.
- **Build-time Event data check**: runs after `pages.py` and prints problem counts (as GitHub warnings). It never blocks the deploy. Today's only finding is that some shows have no performer, which is a recommended field, not a required one.
- **UTM tags on share links**: map share and per-show share now carry `utm_source=share&utm_medium=social`.
- Homepage and footer links to the new pages. The daily workflow now commits the new folders.

## Skipped, and why
- **`/this-weekend/` and `/jazz-brunch/`**: events.json only holds tonight's shows, so weekend pages would be empty or wrong. Possible later if the scraper keeps 3 days of data.
- **Expired-show redirects**: shared shows are `/?show=…` links on the homepage, not separate pages, so nothing expires into a 404.
- **UTM on the Instagram story graphic**: it's an image with no clickable link.

## Check these (written from general knowledge, marked `"verify": true`)
Village Vanguard, Smalls, Mezzrow, Smoke, Zinc Bar, Arthur's Tavern, Cellar Dog, Bill's Place, Bar LunÀtico, Ornithology, Close Up, Bar Bayeux, The Jazz Gallery, Soapbox Gallery, Dizzy's Club. Edit `scraper/venue_notes.json`, and set `verify` to false once checked.

## Submit in Google Search Console after merge
1. Sitemap: `https://word-nyc.com/sitemap.xml` (resubmit)
2. Request indexing:
   - https://word-nyc.com/venues/
   - https://word-nyc.com/guides/best-small-jazz-clubs-nyc/
   - https://word-nyc.com/late-night-jazz/
   - https://word-nyc.com/free-shows/
   - https://word-nyc.com/neighborhood/brooklyn/
   - https://word-nyc.com/neighborhood/greenwich-village/
   - https://word-nyc.com/neighborhood/williamsburg/
   - https://word-nyc.com/neighborhood/harlem/
3. Run the Rich Results Test on a venue page (e.g. /venues/village-vanguard/) to confirm the Event and Breadcrumb data.
