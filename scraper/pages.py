#!/usr/bin/env python3
"""Build the search-friendly pages from events.json: one page per genre, one per venue, an all-shows list,
and sitemap.xml. Runs after the daily lineup is built; every page is plain HTML that search engines can read,
with schema.org Event data so shows can appear in Google's event listings.

  /tonight/                 all shows tonight, as a list
  /tonight/<genre>/         e.g. /tonight/jazz/
  /venues/<venue>/          e.g. /venues/village-vanguard/
  /venues/                  every venue, by neighborhood
  /neighborhood/<area>/     e.g. /neighborhood/greenwich-village/, /neighborhood/brooklyn/
  /late-night-jazz/, /free-shows/
  /guides/best-small-jazz-clubs-nyc/
  /badge/                   "See us on Word NYC" badge snippets for venues
"""
from __future__ import annotations

import html
import json
import math
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, NY, ROOT, minutes, parse_clock  # noqa: E402
from genres import GENRES  # noqa: E402
from areas import area_of  # noqa: E402

SITE = "https://word-nyc.com"
FONTS = ("https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@800"
         "&family=Schibsted+Grotesk:wght@400;600&display=swap")

# Google's Event rich result wants an image on every event, in 16x9, 4x3 and 1x1.
# Most listings arrive without a flyer, so these branded cards stand in for them.
FALLBACK_IMAGES = (f"{SITE}/icons/show-16x9.png", f"{SITE}/icons/show-4x3.png", f"{SITE}/icons/show-1x1.png")


# Every directory pages.py rebuilds from scratch each morning (the workflow commits these).
GENERATED_DIRS = ("tonight", "venues", "neighborhood", "late-night-jazz", "free-shows", "guides", "badge")


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "venue"


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def iso(e: dict) -> str | None:
    m = parse_clock(e.get("time"))
    if m is None or not e.get("date"):
        return None
    d = date.fromisoformat(e["date"])
    return datetime(d.year, d.month, d.day, m // 60, m % 60, tzinfo=NY).isoformat()


def end_iso(e: dict) -> str | None:
    """The show's end time, rolled to the next day when it runs past midnight."""
    start, end = parse_clock(e.get("time")), parse_clock(e.get("end"))
    if end is None or not e.get("date"):
        return None
    d = date.fromisoformat(e["date"])
    dt = datetime(d.year, d.month, d.day, end // 60, end % 60, tzinfo=NY)
    if start is not None and end < start:
        dt += timedelta(days=1)
    return dt.isoformat()


def prices(s: str | None) -> list[float]:
    """Every dollar figure in a free-text price, e.g. '$25 / $40' or 'From$13.60' -> [25.0, 40.0] / [13.6]."""
    if not s:
        return []
    out = []
    for m in re.finditer(r"\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)", s):
        try:
            out.append(float(m.group(1).replace(",", "")))
        except ValueError:
            pass
    return sorted(set(out))


def offer_ld(e: dict) -> dict | None:
    """An Offer for the ticket link, priced when the listing quoted one. A range becomes an AggregateOffer."""
    if not e.get("url"):
        return None
    base = {"url": e["url"], "availability": "https://schema.org/InStock", "priceCurrency": "USD"}
    p = prices(e.get("price"))
    if len(p) > 1:
        return {"@type": "AggregateOffer", "lowPrice": p[0], "highPrice": p[-1], **base}
    if len(p) == 1:
        return {"@type": "Offer", "price": p[0], **base}
    if e.get("price") and re.search(r"\bfree\b|\bno cover\b", e["price"], re.I):
        return {"@type": "Offer", "price": 0, **base}
    return {"@type": "Offer", **base}


def event_ld(e: dict) -> dict:
    ld = {
        "@type": "MusicEvent" if e.get("genre") not in ("Comedy", "Ballet & Dance") else
                 ("ComedyEvent" if e.get("genre") == "Comedy" else "DanceEvent"),
        "name": e["title"], "startDate": iso(e), "endDate": end_iso(e),
        "eventStatus": "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {"@type": "Place", "name": e["venue"],
                     "address": {"@type": "PostalAddress", "streetAddress": e.get("address") or "",
                                 "addressLocality": "New York", "addressRegion": "NY", "addressCountry": "US"}},
    }
    if e.get("performers"):
        ld["performer"] = [{"@type": "PerformingGroup", "name": p} for p in e["performers"][:6]]
    if e.get("description"):
        ld["description"] = e["description"]
    ld["image"] = [e["image"]] if e.get("image") else list(FALLBACK_IMAGES)
    offer = offer_ld(e)
    if offer:
        ld["offers"] = offer
    return {k: v for k, v in ld.items() if v}


LD_PROBLEMS: dict[str, int] = {}


def check_ld(path: str, ld: list[dict]) -> None:
    """Flag Event data Google would reject or downgrade. Logged after the build; never stops it."""
    for o in ld:
        if not str(o.get("@type", "")).endswith("Event"):
            continue
        loc = o.get("location") or {}
        problems = []
        if not o.get("startDate"):
            problems.append("no startDate")
        if not o.get("name"):
            problems.append("no name")
        if not loc.get("name"):
            problems.append("no location name")
        if not (loc.get("address") or {}).get("streetAddress"):
            problems.append("no street address")
        if not o.get("offers"):
            problems.append("no offers (recommended)")
        if not o.get("performer"):
            problems.append("no performer (recommended)")
        for pr in problems:
            LD_PROBLEMS[pr] = LD_PROBLEMS.get(pr, 0) + 1


def report_ld() -> None:
    if not LD_PROBLEMS:
        print("Event data check: no problems")
        return
    print("Event data check (counts are per page an event appears on):")
    for pr, n in sorted(LD_PROBLEMS.items(), key=lambda x: -x[1]):
        level = "warning" if "recommended" in pr else "ERROR"
        print(f"  {level}: {pr}: {n}")
        if level == "ERROR":
            print(f"::warning title=Event data::{n} event entries with {pr}")


def load_geo() -> dict:
    try:
        return json.loads((HERE / "geocache.json").read_text())
    except (OSError, ValueError):
        return {}


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    dy = (a[0] - b[0]) * 111.0
    dx = (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


GENRE_WORDS = {"Jazz": "jazz", "Classical": "classical music", "Opera": "opera", "Ballet & Dance": "dance",
               "Cabaret & Musicals": "cabaret", "Avant-garde": "experimental and new music",
               "Indie & Alternative": "indie and alternative music", "Rock": "rock", "Punk & Hardcore": "punk",
               "Metal": "metal", "Electronic & DJ": "electronic music and DJ nights", "Folk & Americana": "folk and Americana",
               "Country": "country", "Blues": "blues", "Latin": "Latin music", "World": "music from around the world",
               "R&B & Soul": "R&B and soul", "Pop": "pop", "Hip-Hop & Rap": "hip-hop", "Comedy": "comedy",
               "Gospel": "gospel", "Reggae & Caribbean": "reggae and Caribbean music", "African": "African music"}


def page(path: str, title: str, description: str, body: str, ld: list[dict] | None = None,
         crumbs: list[tuple[str, str]] | None = None) -> str:
    """crumbs: [(name, path), ...] after Home, ending with this page; adds a BreadcrumbList and a visible trail."""
    data, trail = "", ""
    if crumbs:
        items = [("Word NYC", "/")] + crumbs
        ld = (ld or []) + [{"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": f"{SITE}{u}"} for i, (n, u) in enumerate(items)]}]
        trail = '    <nav class="crumbs">' + " › ".join(
            f'<a href="{u}">{esc(n)}</a>' for n, u in items[:-1]) + f' › <span>{esc(items[-1][0])}</span></nav>\n'
    if ld:
        check_ld(path, ld)
        data = ('<script type="application/ld+json">' +
                json.dumps({"@context": "https://schema.org", "@graph": ld}, ensure_ascii=False).replace("</", "<\\/") +
                "</script>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{SITE}{path}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{SITE}{path}">
  <meta property="og:image" content="https://word-nyc.com/og.png">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/icons/favicon-32.png">
  <link rel="manifest" href="/manifest.webmanifest">
  <meta name="theme-color" content="#0d1230">
  <link rel="stylesheet" href="{FONTS}">
  <link rel="stylesheet" href="/page.css">
  <link rel="stylesheet" href="/listing.css">
  <meta name="google-adsense-account" content="ca-pub-7078560452492267">
  <script>if(!/WordNYCApp\\//.test(navigator.userAgent)){{var s=document.createElement("script");s.async=true;s.crossOrigin="anonymous";s.src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-7078560452492267";document.head.appendChild(s);}}</script>
  <script defer src="/wn.js"></script>
  <script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token": "2f6bdfef6f95427d91087474b7d81e88"}}'></script>
  {data}
</head>
<body>
  <main class="wrap">
    <a class="home" href="/">Word NYC</a>
{trail}{body}
    <p class="small">Missing a show? <a href="/submit.html?missing=1">Tell us</a> and we'll add it.</p>
    <footer>
      <a href="/">Tonight's map</a><a href="/tonight/">All shows tonight</a><a href="/venues/">Venues</a><a href="/guides/best-small-jazz-clubs-nyc/">Jazz club guide</a><a href="/submit.html">Submit a show</a><a href="/advertise.html">Advertise</a><a href="/privacy.html">Privacy</a>
    </footer>
  </main>
</body>
</html>
"""


def show_item(e: dict, with_venue: bool = True) -> str:
    who = ", ".join(e.get("performers") or [])
    if who and who.lower() == e["title"].lower():
        who = ""
    bits = [f'<span class="t">{esc(e.get("time"))}</span>']
    head = f'<h3>{esc(e["title"])}</h3>'
    if e.get("sponsored"):
        head = '<span class="spon">Sponsored</span>' + head
    meta = []
    if with_venue:
        meta.append(f'<a href="/venues/{slug(e["venue"])}/">{esc(e["venue"])}</a>')
    if e.get("genre") and e["genre"] != "Other":
        meta.append(f'<a href="/tonight/{slug(e["genre"])}/">{esc(e["genre"])}</a>')
    if e.get("price"):
        meta.append(esc(e["price"]))
    extra = f'<p class="who">{esc(who)}</p>' if who else ""
    if e.get("program"):
        extra += f'<p class="prog">{esc("; ".join(e["program"][:6]))}</p>'
    if e.get("description"):
        extra += f'<p class="desc">{esc(e["description"])}</p>'
    link = ""
    if e.get("url"):
        sponsored = "sponsored noopener" if "ticketmaster" in (e.get("source") or "") or "seatgeek" in e["url"] else "noopener"
        link = f'<a class="go" href="{esc(e["url"])}" target="_blank" rel="{sponsored}">Tickets &amp; info</a>'
    return (f'<li class="show">{"".join(bits)}<div class="b">{head}{extra}'
            f'<p class="meta">{" · ".join(meta)}</p>{link}</div></li>')


def show_list(events: list[dict], with_venue: bool = True) -> str:
    return '<ul class="shows">' + "".join(show_item(e, with_venue) for e in events) + "</ul>"


def nice_date(d: date) -> str:
    return d.strftime("%A, %B ") + str(d.day)


def build(out_root: Path = ROOT) -> list[str]:
    data = json.loads((out_root / "events.json").read_text())
    night = date.fromisoformat(data["date"])
    events = sorted(data["events"], key=lambda e: (not e.get("sponsored"), minutes(e.get("time")), e["title"]))
    venues = json.loads((HERE / "venues.json").read_text())["venues"]
    when = nice_date(night)
    paths: list[str] = ["/"]

    for d in GENERATED_DIRS:
        shutil.rmtree(out_root / d, ignore_errors=True)

    def write(path: str, content: str):
        f = out_root / path.strip("/") / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        paths.append(path)

    counts = {g: sum(1 for e in events if e.get("genre") == g) for g in GENRES}
    genre_nav = '<nav class="chips">' + "".join(
        f'<a href="/tonight/{slug(g)}/">{esc(g)} <span>{counts[g]}</span></a>' for g in GENRES if counts[g] and g != "Other") + "</nav>"

    # all shows
    write("/tonight/", page(
        "/tonight/", f"Live music in NYC tonight ({when}) | Word NYC",
        f"{len(events)} live shows in New York tonight: jazz, classical, opera, indie, cabaret and more, with times, "
        "venues and ticket links.",
        f'    <h1>Live music in NYC tonight</h1>\n    <p class="lede">{when}: {len(events)} shows across the city. '
        f'<a href="/">See them on the map</a>.</p>\n    {genre_nav}\n    {show_list(events)}',
        [event_ld(e) for e in events if iso(e)]))

    # one page per genre
    for g in GENRES:
        if g == "Other":
            continue
        evs = [e for e in events if e.get("genre") == g]
        name = "Ballet & dance" if g == "Ballet & Dance" else g
        if evs:
            intro = f'{when}: {len(evs)} {"show" if len(evs) == 1 else "shows"}. ' \
                    f'<a href="/?genre={esc(g)}">See them on the map</a>.'
            body = show_list(evs)
        else:
            intro = f'{when}: nothing listed in this genre yet. The lineup refreshes every morning at 5 AM.'
            body = ""
        write(f"/tonight/{slug(g)}/", page(
            f"/tonight/{slug(g)}/", f"{name} tonight in NYC ({when}) | Word NYC",
            f"{name} in New York tonight: {len(evs)} shows with times, venues, performers and tickets. "
            "Updated every morning.",
            f'    <h1>{esc(name)} in NYC tonight</h1>\n    <p class="lede">{intro}</p>\n    {genre_nav}\n    {body}',
            [event_ld(e) for e in evs if iso(e)]))

    # ---- venues: data shared by the venue, neighborhood, index, guide and badge pages
    notes = json.loads((HERE / "venue_notes.json").read_text()).get("venues", {}) if (HERE / "venue_notes.json").exists() else {}
    geo = load_geo()
    known = {v["name"]: dict(v) for v in venues if not v.get("presenters")}
    for e in events:
        known.setdefault(e["venue"], {"name": e["venue"], "address": e.get("address"), "genre": e.get("genre")})
        if e.get("lat") and e.get("lng"):
            known[e["venue"]].setdefault("lat", e["lat"])
            known[e["venue"]].setdefault("lng", e["lng"])
    for name, v in known.items():
        if not v.get("lat") and geo.get(v.get("address") or ""):
            v["lat"], v["lng"] = geo[v["address"]]
        v["hood"], v["borough"] = area_of(name, v.get("address"))
        v["slug"] = slug(name)
        v["tonight"] = [e for e in events if e["venue"] == name]

    def nearby(v: dict, n: int = 5) -> list[dict]:
        if not v.get("lat"):
            return [w for w in known.values() if w is not v and w.get("hood") and w["hood"] == v.get("hood")][:n]
        cands = [w for w in known.values() if w is not v and w.get("lat")]
        # venues with shows tonight first, then by distance
        return sorted(cands, key=lambda w: (not w["tonight"], km((v["lat"], v["lng"]), (w["lat"], w["lng"]))))[:n]

    def area_label(v: dict) -> str:
        if v.get("hood") and v.get("borough") and v["hood"] not in (v["borough"],):
            return f'{v["hood"]}, {v["borough"]}'
        return v.get("hood") or v.get("borough") or "New York"

    # Neighborhood pages: every neighborhood with 3+ venues, plus Brooklyn and Queens as a whole.
    hood_venues: dict[str, list[dict]] = {}
    for v in known.values():
        if v.get("hood"):
            hood_venues.setdefault(v["hood"], []).append(v)
    areas = {h: vs for h, vs in hood_venues.items() if len(vs) >= 3}
    for b in ("Brooklyn", "Queens"):
        areas[b] = [v for v in known.values() if v.get("borough") == b]
    area_pages = {h: f"/neighborhood/{slug(h)}/" for h in areas}

    def venue_intro(v: dict) -> str:
        note = notes.get(v["name"], {})
        if note.get("about"):
            return note["about"]
        what = GENRE_WORDS.get(v.get("genre") or "", "live music")
        where = area_label(v)
        addr = v.get("address") or ""
        street = addr.split(",")[0] if addr else ""
        s1 = f'{v["name"]} is a {where} venue' + (f" at {street}" if street else "") + f", best known on Word NYC for {what}."
        return s1 + " We read its calendar every morning and list tonight's shows here with times, performers and ticket links."

    # one page per venue (every venue we read, plus any venue with a show tonight)
    for name, v in sorted(known.items()):
        evs = v["tonight"]
        addr = v.get("address") or ""
        maps = f'https://www.google.com/maps/search/?api=1&query={esc(name + " " + addr)}'
        facts = []
        if addr:
            facts.append(f'<a href="{maps}" target="_blank" rel="noopener">{esc(addr)}</a>')
        if v.get("hood") in area_pages:
            facts.append(f'<a href="{area_pages[v["hood"]]}">{esc(v["hood"])}</a>')
        if v.get("url"):
            facts.append(f'<a href="{esc(v["url"])}" target="_blank" rel="noopener">Venue website</a>')
        if v.get("genre") and v["genre"] != "Other":
            facts.append(f'<a href="/tonight/{slug(v["genre"])}/">More {esc(v["genre"])} tonight</a>')
        lede = (f'{when}: {len(evs)} {"show" if len(evs) == 1 else "shows"} tonight.' if evs else
                f'{when}: no shows listed tonight. Check the venue\'s own calendar, or see what\'s on nearby below.')
        near = nearby(v)
        near_html = ""
        if near:
            near_html = ('    <h2>Nearby tonight</h2>\n    <ul class="nearby">' + "".join(
                f'<li><a href="/venues/{w["slug"]}/">{esc(w["name"])}</a>'
                f'<span>{len(w["tonight"]) and str(len(w["tonight"])) + (" show" if len(w["tonight"]) == 1 else " shows") or "no shows listed"}'
                f'{" · " + esc(w["hood"]) if w.get("hood") else ""}</span></li>' for w in near) + "</ul>\n")
        place = {"@type": "MusicVenue", "name": name, "@id": f"{SITE}/venues/{v['slug']}/#venue",
                 "address": {"@type": "PostalAddress", "streetAddress": addr.split(",")[0] if addr else "",
                             "addressLocality": v.get("borough") if v.get("borough") not in (None, "Manhattan") else "New York",
                             "addressRegion": "NY", "addressCountry": "US"}}
        if v.get("lat"):
            place["geo"] = {"@type": "GeoCoordinates", "latitude": v["lat"], "longitude": v["lng"]}
        if v.get("url"):
            place["url"] = v["url"]
        crumbs = [("Venues", "/venues/")]
        if v.get("hood") in area_pages:
            crumbs.append((v["hood"], area_pages[v["hood"]]))
        crumbs.append((name, f"/venues/{v['slug']}/"))
        where = area_label(v)
        write(f"/venues/{v['slug']}/", page(
            f"/venues/{v['slug']}/", f"{name} tonight: schedule & tickets ({when}) | Word NYC",
            f"What's playing at {name} in {where} tonight: set times, performers and tickets. "
            f"{len(evs) or 'No'} {'show' if len(evs) == 1 else 'shows'} listed for {when}.",
            f'    <h1>{esc(name)}</h1>\n'
            f'    <p><button class="fav-btn" type="button" data-fav-venue="{v["slug"]}" data-fav-name="{esc(name)}" hidden>Follow</button></p>\n'
            f'    <p class="facts">{" · ".join(facts)}</p>\n'
            f'    <p class="about">{esc(venue_intro(v))}</p>\n'
            f'    <p class="lede">{lede}</p>\n    {show_list(evs, with_venue=False) if evs else ""}\n{near_html}'
            f'    <p class="small">Run {esc(name)}? <a href="/badge/#{v["slug"]}">Add a "See us on Word NYC" badge</a> '
            f'or <a href="/advertise.html">feature your shows</a>.</p>',
            [place] + [event_ld(e) for e in evs if iso(e)], crumbs))

    # venue index, grouped by borough and neighborhood
    def venue_li(v: dict) -> str:
        n = len(v["tonight"])
        return (f'<li><a href="/venues/{v["slug"]}/">{esc(v["name"])}</a>'
                f'<span>{" · ".join(x for x in (v.get("hood"), str(n) + (" show" if n == 1 else " shows") + " tonight" if n else "") if x)}</span></li>')

    groups = []
    for b in ("Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island", None):
        in_b = sorted((v for v in known.values() if v.get("borough") == b), key=lambda v: (v.get("hood") or "~", v["name"]))
        if not in_b:
            continue
        groups.append(f'    <h2>{esc(b or "Elsewhere")}</h2>\n    <ul class="nearby">' + "".join(venue_li(v) for v in in_b) + "</ul>")
    area_nav = '<nav class="chips">' + "".join(
        f'<a href="{u}">{esc(h)} <span>{sum(len(v["tonight"]) for v in areas[h])}</span></a>'
        for h, u in sorted(area_pages.items())) + "</nav>"
    write("/venues/", page(
        "/venues/", "NYC music venues: jazz clubs, concert halls and indie rooms | Word NYC",
        f"{len(known)} New York music venues Word NYC checks every morning, from jazz clubs and churches to concert "
        "halls and Brooklyn rooms, with tonight's shows at each.",
        f'    <h1>NYC music venues</h1>\n    <p class="lede">The {len(known)} venues we check every morning. '
        f'Pick one to see what it has tonight, or browse by neighborhood.</p>\n    {area_nav}\n' + "\n".join(groups),
        None, [("Venues", "/venues/")]))

    # neighborhood pages
    for h, vs in sorted(areas.items()):
        evs = [e for v in vs for e in v["tonight"]]
        evs.sort(key=lambda e: (not e.get("sponsored"), minutes(e.get("time")), e["title"]))
        is_borough = h in ("Brooklyn", "Queens")
        names = ", ".join(v["name"] for v in sorted(vs, key=lambda v: -len(v["tonight"]))[:4])
        intro = (f"Live music in {h} tonight. Word NYC checks {len(vs)} venues here every morning, "
                 f"including {names}, and lists every show with times and tickets.")
        lede = (f'{when}: {len(evs)} {"show" if len(evs) == 1 else "shows"} tonight.' if evs else
                f'{when}: nothing listed here tonight yet. See <a href="/tonight/">everything playing in NYC</a>.')
        path = area_pages[h]
        write(path, page(
            path, f"Live music in {h} tonight ({when}) | Word NYC",
            f"{len(evs)} live shows in {h}, NYC tonight: jazz, classical, indie and more at {len(vs)} venues "
            "including " + names + ". Updated every morning.",
            f'    <h1>Live music in {esc(h)} tonight</h1>\n    <p class="about">{esc(intro)}</p>\n'
            f'    <p class="lede">{lede}</p>\n    {area_nav}\n    {show_list(evs) if evs else ""}\n'
            f'    <h2>Venues {"in " + esc(h) if is_borough else "in the neighborhood"}</h2>\n'
            f'    <ul class="nearby">' + "".join(venue_li(v) for v in sorted(vs, key=lambda v: v["name"])) + "</ul>",
            [event_ld(e) for e in evs if iso(e)], [("Venues", "/venues/"), (h, path)]))

    # late-night jazz
    def start_min(e: dict) -> int | None:
        return parse_clock(e.get("time"))
    late = [e for e in events if e.get("genre") == "Jazz" and start_min(e) is not None
            and (start_min(e) >= 22 * 60 or start_min(e) < 4 * 60)]
    write("/late-night-jazz/", page(
        "/late-night-jazz/", f"Late-night jazz in NYC tonight ({when}) | Word NYC",
        f"Jazz sets starting at 10 PM or later in New York tonight: {len(late)} late shows at clubs like Smalls, "
        "the Village Vanguard and Bar LunÀtico. Updated every morning.",
        '    <h1>Late-night jazz in NYC tonight</h1>\n'
        '    <p class="about">New York\'s jazz clubs keep going long after dinner. These are tonight\'s sets that start '
        'at 10 PM or later, from second sets at the big rooms to the jam sessions that run past midnight in the '
        'Village and Brooklyn.</p>\n'
        f'    <p class="lede">{when}: ' + (f'{len(late)} late {"set" if len(late) == 1 else "sets"}.' if late else
        'no late sets listed yet. See <a href="/tonight/jazz/">all jazz tonight</a>.') + '</p>\n    ' + show_list(late),
        [event_ld(e) for e in late if iso(e)], [("Jazz tonight", "/tonight/jazz/"), ("Late-night jazz", "/late-night-jazz/")]))

    # free shows
    def is_free(e: dict) -> bool:
        pr = e.get("price") or ""
        return bool(re.search(r"\bfree\b|\bno cover\b|^\$?0(\.00)?$", pr, re.I))
    free = [e for e in events if is_free(e)]
    write("/free-shows/", page(
        "/free-shows/", f"Free live music in NYC tonight ({when}) | Word NYC",
        f"Free concerts and no-cover shows in New York tonight: {len(free)} listed, with times and venues. "
        "Updated every morning.",
        '    <h1>Free live music in NYC tonight</h1>\n'
        '    <p class="about">Shows tonight with free admission or no cover charge: church concerts, school recitals, '
        'bar sets and more. Some clubs still ask for a drink minimum, so check the listing before you go.</p>\n'
        f'    <p class="lede">{when}: ' + (f'{len(free)} free {"show" if len(free) == 1 else "shows"}.' if free else
        'no free shows listed yet. Prices aren\'t always published, so also browse <a href="/tonight/">everything tonight</a>.')
        + '</p>\n    ' + show_list(free),
        [event_ld(e) for e in free if iso(e)], [("Free shows", "/free-shows/")]))

    # guide: best small jazz clubs (text lives in venue_notes.json)
    guide_names = ["Village Vanguard", "Smalls Jazz Club", "Mezzrow", "Smoke Jazz Club", "Zinc Bar", "Arthur's Tavern",
                   "Cellar Dog", "The Jazz Gallery", "Close Up", "Bill's Place", "Bar LunÀtico", "Ornithology Jazz Club",
                   "Bar Bayeux", "Soapbox Gallery"]
    items = []
    for n in guide_names:
        v = known.get(n)
        if not v:
            continue
        today_bit = (f' Tonight: {len(v["tonight"])} {"show" if len(v["tonight"]) == 1 else "shows"}.'
                     if v["tonight"] else "")
        items.append(f'    <h2><a href="/venues/{v["slug"]}/">{esc(n)}</a></h2>\n'
                     f'    <p class="small">{esc(area_label(v))}' + (f' · {esc(v["address"].split(",")[0])}' if v.get("address") else "") + '</p>\n'
                     f'    <p>{esc(notes.get(n, {}).get("about") or venue_intro(v))}{esc(today_bit)}</p>')
    write("/guides/best-small-jazz-clubs-nyc/", page(
        "/guides/best-small-jazz-clubs-nyc/", "The best small jazz clubs in NYC (2026 guide) | Word NYC",
        "Where to hear jazz up close in New York: the Village Vanguard, Smalls, Mezzrow, Smoke, Bar LunÀtico and more "
        "small rooms in Manhattan and Brooklyn, with what's playing tonight.",
        '    <h1>The best small jazz clubs in NYC</h1>\n'
        '    <p class="lede">Big halls are great, but jazz in New York lives in small rooms: basements in the Village, '
        'neighborhood bars in Brooklyn, a brownstone in Harlem. Here are the ones worth knowing, each linked to '
        'what it has on tonight.</p>\n' + "\n".join(items) +
        '\n    <p>Want everything at once? <a href="/tonight/jazz/">See all jazz tonight</a> or '
        '<a href="/late-night-jazz/">just the late sets</a>.</p>',
        [{"@type": "ItemList", "name": "Small jazz clubs in NYC", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "url": f"{SITE}/venues/{slug(n)}/", "name": n}
            for i, n in enumerate(x for x in guide_names if x in known)]}],
        [("Guides", "/guides/best-small-jazz-clubs-nyc/"), ("Small jazz clubs", "/guides/best-small-jazz-clubs-nyc/")]))

    # badge page for venues to link back
    opts = "".join(f'<option value="{v["slug"]}">{esc(n)}</option>' for n, v in sorted(known.items()))
    write("/badge/", page(
        "/badge/", "Add the Word NYC badge to your venue's website | Word NYC",
        "Free badge for NYC music venues: show visitors where to find your tonight's lineup on Word NYC.",
        '    <h1>Add the Word NYC badge</h1>\n'
        '    <p class="lede">Free for every venue we list. Paste this on your website (footer or calendar page) '
        'and visitors can see tonight\'s lineup at your venue, alongside everything else playing in NYC.</p>\n'
        '    <p><label for="v">Your venue</label><br><select id="v">' + opts + '</select></p>\n'
        '    <p><img id="pv" src="/icons/badge.svg" width="180" height="44" alt="See us on Word NYC"></p>\n'
        '    <textarea id="code" readonly rows="4" style="width:100%;font:13px monospace;background:var(--ink-2);'
        'color:var(--paper);border:1px solid var(--line);border-radius:10px;padding:10px"></textarea>\n'
        '    <p><button class="btn" id="cp" type="button">Copy code</button></p>\n'
        '    <p class="small">Not listed yet? <a href="/submit.html">Submit your venue</a>. Want your shows at the top of '
        'the map? <a href="/advertise.html">Feature them</a>.</p>\n'
        '    <script>(function(){var s=document.getElementById("v"),c=document.getElementById("code");'
        'function u(){var h="https://word-nyc.com/venues/"+s.value+"/?utm_source=badge&utm_medium=referral";'
        'c.value=\'<a href="\'+h+\'"><img src="https://word-nyc.com/icons/badge.svg" width="180" height="44" '
        'alt="See us on Word NYC"></a>\';history.replaceState(null,"","#"+s.value);}'
        'var k=location.hash.slice(1);if(k&&s.querySelector(\'option[value="\'+k+\'"]\'))s.value=k;'
        's.addEventListener("change",u);u();document.getElementById("cp").addEventListener("click",function(){'
        'c.select();try{navigator.clipboard.writeText(c.value);this.textContent="Copied";}catch(e){document.execCommand("copy");}});})();'
        '</script>',
        None, [("Badge", "/badge/")]))

    # sitemap
    static = ["/submit.html", "/advertise.html", "/privacy.html"]
    today = night.isoformat()
    urls = "".join(f"  <url><loc>{SITE}{p}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>\n"
                   for p in paths if p != "/badge/") + "".join(f"  <url><loc>{SITE}{p}</loc></url>\n" for p in static + ["/badge/"])
    (out_root / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                          f"{urls}</urlset>\n")
    report_ld()
    return paths


if __name__ == "__main__":
    built = build()
    print(f"Wrote {len(built)} pages and sitemap.xml")
