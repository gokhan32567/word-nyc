#!/usr/bin/env python3
"""Build the search-friendly pages from events.json: one page per genre, one per venue, an all-shows list,
and sitemap.xml. Runs after the daily lineup is built; every page is plain HTML that search engines can read,
with schema.org Event data so shows can appear in Google's event listings.

  /tonight/                 all shows tonight, as a list
  /tonight/<genre>/         e.g. /tonight/jazz/
  /venues/<venue>/          e.g. /venues/village-vanguard/
"""
from __future__ import annotations

import html
import json
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, NY, ROOT, minutes, parse_clock  # noqa: E402
from genres import GENRES  # noqa: E402

SITE = "https://word-nyc.com"
FONTS = ("https://fonts.googleapis.com/css2?family=Big+Shoulders+Display:wght@800"
         "&family=Schibsted+Grotesk:wght@400;600&display=swap")


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


def event_ld(e: dict) -> dict:
    ld = {
        "@type": "MusicEvent" if e.get("genre") not in ("Comedy", "Ballet & Dance") else
                 ("ComedyEvent" if e.get("genre") == "Comedy" else "DanceEvent"),
        "name": e["title"], "startDate": iso(e),
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
    if e.get("image"):
        ld["image"] = [e["image"]]
    if e.get("url"):
        ld["offers"] = {"@type": "Offer", "url": e["url"], "availability": "https://schema.org/InStock"}
    return {k: v for k, v in ld.items() if v}


def page(path: str, title: str, description: str, body: str, ld: list[dict] | None = None) -> str:
    data = ""
    if ld:
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
  <meta name="theme-color" content="#0d1230">
  <link rel="stylesheet" href="{FONTS}">
  <link rel="stylesheet" href="/page.css">
  <link rel="stylesheet" href="/listing.css">
  <script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{{"token": "2f6bdfef6f95427d91087474b7d81e88"}}'></script>
  {data}
</head>
<body>
  <main class="wrap">
    <a class="home" href="/">Word NYC</a>
{body}
    <footer>
      <a href="/">Tonight's map</a><a href="/tonight/">All shows tonight</a><a href="/submit.html">Submit a show</a><a href="/advertise.html">Advertise</a><a href="/privacy.html">Privacy</a>
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

    for d in ("tonight", "venues"):
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

    # one page per venue (every venue we read, plus any venue with a show tonight)
    known = {v["name"]: v for v in venues if not v.get("presenters")}
    for e in events:
        known.setdefault(e["venue"], {"name": e["venue"], "address": e.get("address"), "genre": e.get("genre")})
    for name, v in sorted(known.items()):
        evs = [e for e in events if e["venue"] == name]
        addr = v.get("address") or ""
        maps = f'https://www.google.com/maps/search/?api=1&query={esc(name + " " + addr)}'
        facts = []
        if addr:
            facts.append(f'<a href="{maps}" target="_blank" rel="noopener">{esc(addr)}</a>')
        if v.get("url"):
            facts.append(f'<a href="{esc(v["url"])}" target="_blank" rel="noopener">Venue website</a>')
        if v.get("genre") and v["genre"] != "Other":
            facts.append(f'<a href="/tonight/{slug(v["genre"])}/">More {esc(v["genre"])} tonight</a>')
        lede = (f'{when}: {len(evs)} {"show" if len(evs) == 1 else "shows"} tonight.' if evs else
                f'{when}: no shows listed tonight. Check the venue\'s own calendar, or see '
                f'<a href="/tonight/">everything playing tonight</a>.')
        place = {"@type": "MusicVenue", "name": name,
                 "address": {"@type": "PostalAddress", "streetAddress": addr, "addressLocality": "New York",
                             "addressRegion": "NY", "addressCountry": "US"}}
        if v.get("url"):
            place["url"] = v["url"]
        write(f"/venues/{slug(name)}/", page(
            f"/venues/{slug(name)}/", f"{name}: shows tonight ({when}) | Word NYC",
            f"What's playing at {name} tonight: times, performers and tickets. {addr}".strip(),
            f'    <h1>{esc(name)}</h1>\n    <p class="facts">{" · ".join(facts)}</p>\n'
            f'    <p class="lede">{lede}</p>\n    {show_list(evs, with_venue=False) if evs else ""}',
            [place] + [event_ld(e) for e in evs if iso(e)]))

    # sitemap
    static = ["/submit.html", "/advertise.html", "/privacy.html"]
    today = night.isoformat()
    urls = "".join(f"  <url><loc>{SITE}{p}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>\n"
                   for p in paths) + "".join(f"  <url><loc>{SITE}{p}</loc></url>\n" for p in static)
    (out_root / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                          f"{urls}</urlset>\n")
    return paths


if __name__ == "__main__":
    built = build()
    print(f"Wrote {len(built)} pages and sitemap.xml")
