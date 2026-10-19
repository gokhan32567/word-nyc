# Word NYC (word-nyc.com)

A live map of tonight's music shows in New York. The lineup refreshes automatically at **5:00 AM New York time every day**.

- `index.html`: the whole site (map, list, genre filters, show details, story-graphic sharing)
- `submit.html`: "Submit a show" form for artists and venues (also brings in sponsorship leads)
- `coverage.html`: the daily venue coverage report (not linked from the site, not indexed)
- `advertise.html`, `privacy.html`, `page.css`: the Advertise and Privacy pages
- `events.json`: tonight's lineup, rewritten each morning by the workflow
- `coverage.json`: what each venue produced this morning
- `sponsored.json`: paid placements you sell to venues (edit by hand)
- `scraper/`: builds `events.json` (Python; Playwright for the browser, everything else standard library)
- `scraper/venues.json`: the venues read every morning (add your own)
- `.github/workflows/update-events.yml`: the daily 5 AM job

## Setup

The site is live at <https://word-nyc.com> (GitHub Pages, repo `gokhan32567/word-nyc`). Secrets live in
repo → Settings → Secrets and variables → Actions.

| Secret / variable | What it turns on | Where to get it |
|---|---|---|
| `TICKETMASTER_API_KEY` (secret) | Ticketmaster, TicketWeb and Universe shows | Consumer Key of an app at <https://developer.ticketmaster.com> |
| `ANTHROPIC_API_KEY` (secret) | AI reading of venue calendars | <https://console.anthropic.com> → API keys. Add a few dollars of credit and set a monthly spend limit. |
| `EVENTBRITE_TOKEN` (secret, optional) | Eventbrite organizer feeds for venues that have an `eventbrite` id | Eventbrite → Account settings → Developer links → API keys → private token |
| `SUBMISSIONS_CSV_URL` (variable, optional) | Approved form submissions | See "Submit a show" below |

Run the job by hand: Actions → *Update tonight's lineup* → *Run workflow*. Type a few venue names in the box
(e.g. `Smalls, Birdland`) for a test run that reads only those venues and doesn't publish.

Before relying on it commercially: review `privacy.html` (a template, not legal advice).

## Making money

All three switch on by pasting an ID into the `CONFIG` block near the top of the script in `index.html`. Until then the site works the same, without them.

### 1. Ticket commissions (`affiliate`)

| Program | Network | What to paste |
|---|---|---|
| Ticketmaster | Impact | `affiliate.ticketmaster`: the Impact tracking link Impact gives you for Ticketmaster. Ticket URLs are appended as `?u=`. If you also add your Impact publisher ID to your Ticketmaster developer account, links from the API arrive already tracked and are left as they are. |
| SeatGeek | Impact | `affiliate.seatgeekAid`: your SeatGeek partner ID, added to SeatGeek links as `?aid=`. |

- Apply through each program's page on Impact. Ticketmaster suggests emailing them first to check you qualify.
- Ticketmaster pays only on completed sales, and not on presales or in the first 24 hours after a show goes on sale.
- Commission links get `rel="sponsored"` and a short "may earn a commission" note under the ticket button, plus a line in the listings footer (the FTC expects affiliate links to be disclosed).
- Ticketmaster's API terms restrict earning money from their data outside their partner programs; read them and confirm your use with Ticketmaster before relying on it commercially.

### 2. Sponsored listings (`sponsored.json`)

Usually the best earner for a local site: venues pay to be featured. A sponsored show goes to the top of the list until it ends, gets a highlighted pin and appears first in the share graphic. It is always labeled **Sponsored**.

Edit `sponsored.json` on GitHub (pencil icon); saving it republishes tonight's lineup within a couple of minutes.

```json
{
  "placements": [
    { "venue": "Blue Note Jazz Club", "from": "2026-11-01", "until": "2026-11-30" },
    { "venue": "Carnegie Hall", "title_contains": "Beethoven", "from": "2026-11-14", "until": "2026-11-14" },
    { "event": { "title": "Album Release Show", "performers": ["Example Band"], "venue": "Baby's All Right",
                 "address": "146 Broadway, Brooklyn, NY", "lat": 40.7101, "lng": -73.9626, "time": "9:00 PM",
                 "genre": "Indie Rock", "price": "$18", "url": "https://example.com/tickets" },
      "from": "2026-11-07", "until": "2026-11-07" }
  ]
}
```

- `venue` matches the venue name; `title_contains` narrows it to one show.
- `event` adds a show the daily sources don't list (it needs at least `title`, `venue`, `lat`, `lng`, `time`).
- The Advertise page (`advertise.html`) is where venues find you.

### 3. Display ads (`adsense`) and visitor counts (`analyticsToken`)

- **AdSense:** apply at <https://adsense.google.com> with your own domain (AdSense needs a domain you control).
  Once approved, create a display ad unit and paste `client` (`ca-pub-…`) and `slot`. The site shows one ad below the listings; it loads once and never auto-refreshes, which AdSense forbids.
  Also add an `ads.txt` file at the root of the repo containing the line AdSense shows you
  (`google.com, pub-…, DIRECT, f08c47fec0942fa0`), and turn on AdSense's consent message for visitors in Europe and US states that require it (AdSense → Privacy & messaging).
- **Visitor counts:** create a free Cloudflare Web Analytics site and paste its token into `analyticsToken`. It's cookie-free, and the numbers are what sponsors will ask for.

## Where the shows come from

Every morning the job reads, in this order:

1. **Venue calendars** (`scraper/venues.json`, about 150 venues: jazz clubs, concert halls, church concert
   series, new-music spaces, indie rooms). A real browser (headless Chromium) opens each venue's calendar page.
   If the page doesn't mention tonight's date, it follows the page's "calendar"/"events" link once. Then the
   first method that works is used:
   - schema.org event data embedded in the page (JSON-LD);
   - The Events Calendar for WordPress (its public REST API);
   - an iCal feed linked from the page (or the venue's `ical` field);
   - an Eventbrite organizer feed (the venue's `eventbrite` id, needs `EVENTBRITE_TOKEN`);
   - **AI reading**: Claude Haiku reads the page text and reports tonight's shows (title, performers, time,
     program, price). Each show is then checked against the page itself: the date and time it quotes must
     appear on the page and be tonight, the title must be on the page, and performers, program and price are
     kept only if they're on the page too. Anything else is thrown out. Descriptions are short and in our own
     words (a description that copies the page is dropped).
2. **Ticketmaster Discovery API**: ticketed shows within ~12 miles of lower Manhattan (NY state only), which
   also covers TicketWeb venues such as Birdland.
3. **Approved submissions** from the Submit form.
4. **Sponsored placements** in `sponsored.json`.

When the same show turns up in more than one source (same venue, same start time, overlapping names), the
records are merged and each fills in what the other is missing; the Ticketmaster ticket link wins. Shows read
from a venue's own calendar carry a "Listing from {venue}'s calendar" note linking back to that page. If
**every** source fails, the job leaves the previous `events.json` in place and retries at the next scheduled time.

Limits: the browser identifies itself as Word NYC, respects each site's `robots.txt`, and loads one page per
venue (plus at most one calendar link). Some sites block automated visitors outright (they show as *Blocked*
in the coverage report). Check a venue's terms if in doubt; the site only republishes facts (who, when,
where, price) with a link back.

### Adding a venue

Add an entry to `scraper/venues.json`:

```json
{ "name": "Smalls Jazz Club", "address": "183 W 10th St, New York, NY 10014",
  "url": "https://www.smallslive.com/", "genre": "Jazz" }
```

- `url`: the venue's calendar or events page (the more specific, the better and cheaper).
- `genre`: used when the page doesn't say. Any label works; it's grouped by `scraper/genres.py`.
- Optional: `lat`/`lng` (otherwise the address is looked up once on OpenStreetMap and cached in
  `scraper/geocache.json`), `ical` (feed URL), `eventbrite` (organizer id), `method: "tribe"` (force the
  WordPress calendar API), `note` (an instruction for the AI reader, e.g. "Only concerts in the Sanctuary"), `strict` (true/false: whether
  titles need a performance word), `narrow: true` (read the page at phone width), `via` (don't read this site; its
  shows come from another entry's calendar), `presenters` (a campus calendar: maps each presenting organization to
  the venue entry its shows go to; see the Lincoln Center entry).

### Coverage report

Each run writes `coverage.json`, viewable at <https://word-nyc.com/coverage.html>, and a summary on the
run's page in the Actions tab. Every venue gets a status: *Shows found*, *Nothing tonight*, *Blocked*,
*Didn't load*, *Asks not to be read* (robots.txt), *Address not found*, or *Not read* (no AI key). A venue
that's blocked or broken day after day needs a better `url` (its calendar page, an iCal feed) or removal.

### Cost

GitHub's servers are free for a public repo. AI reading costs about $0.10 per million input tokens and
$0.50 per million output tokens (Claude Haiku 5.5); a page is capped at ~24,000 characters, so a full
morning is roughly 150 pages × ~7,000 tokens ≈ $0.10–0.30, or about $5–10 a month. The coverage report
shows each run's actual token use and cost. Change the model with the `AI_MODEL` environment variable.

## Submit a show

`submit.html` collects show title, performers, venue, address, date, start time, genre, price, link,
a short description and the submitter's email.

- **Until a Google Form is connected**, pressing *Send show* opens an email draft to
  `advertise@word-nyc.com` (set up forwarding for that address at Porkbun → Email).
- **To collect submissions in a sheet:** create a Google Form with those questions plus an **Approved**
  column in its response sheet. Put the form's `formResponse` URL and each question's `entry.…` id into
  `GOOGLE_FORM` at the bottom of `submit.html`. Then in the sheet: File → Share → Publish to web →
  the responses sheet as CSV, and save that link as the repo variable `SUBMISSIONS_CSV_URL`. Rows where
  *Approved* is `yes` are added on their date. Columns are matched by name (date, start time, venue name,
  address, title, performers, ticket link, genre, price, description).

## What each show carries

Clicking a show on the map or in the list opens its details: show name, performers, date and time (with end time when the source gives one), venue and street address, program (works performed), ticket price, a short description, a photo, a tickets link and an "Open in Maps" link. Fields a source doesn't provide are simply left out.

`events.json` fields: `title`, `performers`, `venue`, `address`, `lat`, `lng`, `date`, `time`, `end`, `genre`, `subgenre`, `price`, `program`, `description`, `image`, `url` (plus `artist`, kept for older page versions).

## Genres

Raw genres from each source are grouped into: Opera, Ballet & Dance, Classical, Avant-garde, Jazz, Blues, Gospel, R&B & Soul, Hip-Hop & Rap, Reggae & Caribbean, Latin, African, Electronic & DJ, Metal, Punk & Hardcore, Indie & Alternative, Rock, Country, Folk & Americana, Pop, World, Cabaret & Musicals, Comedy, Other.
Edit the patterns in `scraper/genres.py` to change how shows are grouped. For venue calendars, the `genre` in `venues.json` is used when the venue's page doesn't say. The site only shows chips for genres that have shows that night.

On the site, genre chips filter the map, the list and the share graphic. Selections are remembered and added to the URL, so `?genre=Jazz,Latin` links straight to a filtered view.

## Schedule details

GitHub schedules run in UTC, so the workflow fires at 09:00, 10:00 and 11:00 UTC and only does work when tonight's lineup isn't published yet. That gives 5:00 AM year-round (daylight saving included) plus a retry. GitHub can delay scheduled runs by several minutes at busy times. If the update hasn't landed yet when someone opens the page after 5 AM, it shows the previous lineup with a note and re-checks every 10 minutes.

Run it locally:

```bash
pip install playwright==1.56.0 && python -m playwright install chromium
TICKETMASTER_API_KEY=xxxx ANTHROPIC_API_KEY=xxxx python scraper/scrape.py   # tonight
python scraper/scrape.py --date 2026-10-31 --out /tmp/test.json            # a specific night
python scraper/scrape.py --only "smalls,birdland"                            # a few venues
python scraper/scrape.py --no-browser                                        # Ticketmaster etc. only
```

## Before going commercial

- **Ticketmaster:** follow the Discovery API terms (attribution, linking to Ticketmaster for tickets). Their affiliate program can pay commission on ticket links.
- **Venue sites:** check each site's terms before reading it commercially; asking venues for a feed or partnership is the durable route. Remove a venue from `venues.json` if it asks.
- **Map:** OpenFreeMap is free for commercial use; keep the OpenStreetMap credit visible (already on the map and the share image).
