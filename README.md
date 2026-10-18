# Word NYC (word-nyc.com)

A live map of tonight's music shows in New York. The lineup refreshes automatically at **5:00 AM New York time every day**.

- `index.html`: the whole site (map, list, genre filters, show details, story-graphic sharing)
- `advertise.html`, `privacy.html`, `page.css`: the Advertise and Privacy pages
- `events.json`: tonight's lineup, rewritten each morning by the workflow
- `sponsored.json`: paid placements you sell to venues (edit by hand)
- `scraper/`: builds `events.json` (Python, standard library only)
- `.github/workflows/update-events.yml`: the daily 5 AM job

## Launch checklist

1. **Create the repo and turn on GitHub Pages:** push these files to a public repo, then
   Settings → Pages → Source: *Deploy from a branch* → `main` / `(root)` → Save.
   The site appears at `https://<your-username>.github.io/<repo-name>/`.
2. **Add the Ticketmaster key** (main data source, free):
   - Create an app at <https://developer.ticketmaster.com> and copy its *Consumer Key*.
   - Repo → Settings → Secrets and variables → Actions → *New repository secret*
     → Name `TICKETMASTER_API_KEY`, value = the key.
3. **Run it once now:** Actions tab → *Update tonight's lineup* → *Run workflow*.
   After that it runs on its own every morning. Until the first run, the page shows sample shows.
4. **Use your own domain** (needed for AdSense, and better for a business): buy one from any registrar,
   then Settings → Pages → *Custom domain*, and follow GitHub's DNS instructions
   (<https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site>). Tick *Enforce HTTPS*.
5. **Fill in your details:**
   - the contact emails in `advertise.html` and `privacy.html` (search for `your-domain.com`);
   - `siteLabel` in `index.html` (shown at the bottom of the share graphic; put your domain there).
6. **Review `privacy.html`.** It's a template matching how the site works, not legal advice.

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

| Source | What it adds | Notes |
|---|---|---|
| Ticketmaster Discovery API | Most ticketed shows within ~12 miles of lower Manhattan, with genre | Needs the free key above. 5,000 calls/day free; the job uses ~5. |
| Venue calendars in `scraper/venues.json` | Venues that sell tickets elsewhere (jazz clubs, Lincoln Center, Carnegie Hall, BAM, the Joyce, Roulette, The Stone…) | Only works for sites that publish schema.org event data. The job log shows how many shows each venue returned; a venue showing 0 every day needs a custom parser or removal. |

When the same show turns up in more than one source (same venue, same start time, overlapping names), the records are merged into one and each fills in what the other is missing: the venue page usually supplies the program, Ticketmaster the price range and photo. If **every** source fails, the job leaves the previous `events.json` in place and retries at the next scheduled time.

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
TICKETMASTER_API_KEY=xxxx python scraper/scrape.py            # tonight
python scraper/scrape.py --date 2026-10-31 --out /tmp/test.json # a specific night
```

## Before going commercial

- **Ticketmaster:** follow the Discovery API terms (attribution, linking to Ticketmaster for tickets). Their affiliate program can pay commission on ticket links.
- **Venue sites:** check each site's terms before scraping commercially; asking venues for a feed or partnership is the durable route.
- **Map:** OpenFreeMap is free for commercial use; keep the OpenStreetMap credit visible (already on the map and the share image).
