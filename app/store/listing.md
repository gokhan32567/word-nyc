# App Store listing: Word NYC

Paste these into App Store Connect → your app → the version page (and App Information). Character limits
are Apple's; every field below fits.

## App Information

| Field | Value |
|---|---|
| Name (30) | `Word NYC: Live Music Tonight` |
| Subtitle (30) | `Jazz, opera and gigs on a map` |
| Bundle ID | `com.wordnyc.app` |
| SKU | `word-nyc-ios` |
| Primary category | Music |
| Secondary category | Entertainment |
| Content rights | Yes, it shows third-party content (show listings: facts and links from venues and ticket sellers) and you have the rights to use it. Same basis as the website: only who, when, where and price, with links back. |
| Age rating | Answer **None / No** to every question. "Unrestricted web access": **No** (links open single pages in Safari's in-app view; the app has no browser of its own). Expected result: 4+. |
| Price | Free |
| Availability | All countries (visitors plan trips from abroad), or United States only if you prefer |

## Version 1.0

**Promotional text (170)**, can be changed any time without review:

> Tonight's live music in New York on one map: jazz clubs, indie rooms, the Met and Carnegie Hall. Updated every morning, with a noon pick of the best shows.

**Description (4000):**

> Word NYC shows you what's playing in New York tonight, on one live map.
>
> Every morning at 5 AM, Word NYC reads the calendars of more than 150 venues, from Village Vanguard, Smalls and Blue Note to Carnegie Hall, the Met, Roulette, Bowery Ballroom and Brooklyn Steel, and puts tonight's shows on a map. Gold pins are playing right now, so you can see at a glance where the music is.
>
> WHAT'S ON, RIGHT NOW
> • Every show tonight on a map of the city, with what's live, starting soon and later
> • Set times, performers, program and ticket prices
> • Filter by jazz, classical, opera, dance, indie, rock, Latin, electronic and more
> • Tap a show for details, tickets and directions in Apple Maps
>
> TONIGHT'S PICKS AT NOON
> Turn on one notification a day, at noon, with a few of the night's best shows. Follow the venues you love with the heart, and the noon pick tells you when they have a show tonight. Turn it off any time.
>
> MADE FOR GOING OUT
> • Works on the subway: the app keeps tonight's lineup on your phone
> • Share a show, or a story-ready image of tonight's map, to Instagram and Messages
> • No account, no sign-up, no ads
>
> Word NYC lists shows; it doesn't sell tickets. "Get tickets" opens the venue's or ticket seller's own page. Some ticket links earn Word NYC a commission at no extra cost to you, and venues can pay to feature a show, which is always labeled Sponsored.
>
> Venues change their plans, so check the venue's own listing before you go. Missing a show? Tell us from the app.

**Keywords (100):**

```
jazz,concerts,gigs,shows,nyc,new york,classical,opera,indie,clubs,events,brooklyn,manhattan,bands
```

(Words already in the name, like "live", "music" and "tonight", are indexed from the name and don't need repeating.)

| Field | Value |
|---|---|
| Support URL | `https://word-nyc.com/support.html` |
| Marketing URL | `https://word-nyc.com/` |
| Privacy Policy URL | `https://word-nyc.com/privacy.html` |
| Copyright | `2026 Gokhan Yilmaz` |
| Version | `1.0.0` (set by the build) |

**What's New** (only from the second version on): leave empty for 1.0.

## Screenshots

`app/store/screenshots/` (6.9-inch iPhone, 1320 × 2868): the app's own screens with the app's user agent (no
ads), its safe areas and an iPhone status bar, rendered by **Actions → App Store screenshots (Linux)**. Upload
them in this order under "iPhone 6.9" Display"; App Store Connect scales them for smaller iPhones. The app is
iPhone-only, so no iPad screenshots are needed.

1. `1-map.png`: the map with tonight's shows (caption idea: "Tonight's live music, on one map")
2. `2-list.png`: the full list, live shows lit gold ("See what's playing right now")
3. `3-show.png`: a show's details with tickets and directions ("Times, tickets and directions")
4. `4-jazz.png`: filtered to jazz ("Jazz, classical, indie and more")
5. `5-venue.png`: a venue page with the Follow heart ("Follow your favorite venues")

To take fresh ones (the lineup changes daily): Actions → App Store screenshots (Linux) → Run workflow. (The
"screenshots" option of the iOS app workflow uses the real simulator, but CI simulators have no GPU, so the
map takes 20+ minutes there.)

## App icon

`app/store/app-icon-1024.png` is the icon built into the app (App Store Connect takes it from the build;
you don't upload it separately).
