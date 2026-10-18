#!/usr/bin/env python3
"""Build events.json with tonight's NYC music shows.

"Tonight" runs from 5:00 AM today to 5:00 AM tomorrow, New York time, matching the page.

Sources (each optional, failures are logged and skipped):
  1. Venue calendars (venues.json)  - pages that publish schema.org Event JSON-LD
  2. Ticketmaster Discovery API     - needs TICKETMASTER_API_KEY (free at developer.ticketmaster.com)

Each event in events.json:
  title        show name ("La Bohème", "Mahler's Fifth Symphony", "Big Thief")
  performers   list of performers (may be empty when the title is the performer)
  artist       performers joined, or the title (kept for older page versions)
  venue, address, lat, lng
  date         YYYY-MM-DD (calendar date the show starts)
  time, end    "8:00 PM" ("end" only when the source says)
  genre        one of the site's buckets (see genres.py); subgenre = the source's own label
  price        "$25", "$35–$120", "Free"
  program      list of works performed (classical, opera, dance)
  description  short text from the source
  image, url   picture and tickets/info link

Usage:
  python scraper/scrape.py                     # writes events.json in the repo root
  python scraper/scrape.py --out path.json
  python scraper/scrape.py --date 2026-10-18   # build for a specific night
Standard library only.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from genres import GENRES, VAGUE, bucket  # noqa: E402

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
ROLLOVER_HOUR = 5
CENTER = (40.7300, -73.9950)   # lower Manhattan
RADIUS_MILES = 12              # covers Manhattan, most of Brooklyn and Queens
USER_AGENT = "WordNYC/1.0 (+https://word-nyc.com; daily lineup builder)"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- small helpers

def night_window(night: date) -> tuple[datetime, datetime]:
    start = datetime(night.year, night.month, night.day, ROLLOVER_HOUR, tzinfo=NY)
    return start, start + timedelta(days=1)


def current_night() -> date:
    return (datetime.now(NY) - timedelta(hours=ROLLOVER_HOUR)).date()


def clock(dt: datetime) -> str:
    """datetime -> '8:00 PM' in New York time."""
    dt = dt.astimezone(NY)
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{1,2}):(\d{2}))?", v)
        if not m:
            return None
        d = date.fromisoformat(m.group(1))
        dt = datetime(d.year, d.month, d.day, int(m.group(2) or 0), int(m.group(3) or 0))
    return dt if dt.tzinfo else dt.replace(tzinfo=NY)


def has_time(value: str) -> bool:
    return bool(re.search(r"[T ]\d{1,2}:\d{2}", value or ""))


def clean_text(value, limit: int = 420) -> str | None:
    if not value:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


def money(v: float, cur: str) -> str:
    s = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return f"${s}" if cur in ("", "USD") else f"{s} {cur}"


def price_label(lo, hi=None, cur: str = "USD") -> str | None:
    try:
        lo = float(lo) if lo not in (None, "") else None
        hi = float(hi) if hi not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if lo is None and hi is None:
        return None
    lo = hi if lo is None else lo
    cur = (cur or "USD").upper()
    first = "Free" if lo == 0 else money(lo, cur)
    if hi is None or hi == lo:
        return first
    return f"{first}–{money(hi, cur)}"


def names_of(x) -> list[str]:
    """Names from a JSON-LD value that may be a string, a dict or a list of either."""
    items = x if isinstance(x, list) else [x]
    out = []
    for it in items:
        name = it.get("name") if isinstance(it, dict) else it
        name = html.unescape(str(name or "")).strip()
        if name and name not in out:
            out.append(name)
    return out


def address_of(a) -> str | None:
    if isinstance(a, list):
        a = a[0] if a else None
    if isinstance(a, str):
        return clean_text(a, 160)
    if isinstance(a, dict):
        parts = [a.get("streetAddress"), a.get("addressLocality"), a.get("addressRegion")]
        return ", ".join(str(p).strip() for p in parts if p) or None
    return None


def image_of(x) -> str | None:
    if isinstance(x, list):
        x = x[0] if x else None
    if isinstance(x, dict):
        x = x.get("url") or x.get("contentUrl")
    return x if isinstance(x, str) and x.startswith("http") else None


# ---------------------------------------------------------------- http

def get(url: str, params: dict | None = None, timeout: int = 25) -> str:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------- Ticketmaster

_GH = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lng: float, precision: int = 9) -> str:
    lat_r, lng_r, bits, out, ch, even = [-90.0, 90.0], [-180.0, 180.0], 0, [], 0, True
    while len(out) < precision:
        rng, val = (lng_r, lng) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch = (ch << 1) | 1
            rng[0] = mid
        else:
            ch <<= 1
            rng[1] = mid
        even, bits = not even, bits + 1
        if bits == 5:
            out.append(_GH[ch])
            bits, ch = 0, 0
    return "".join(out)


def utc_param(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_ticketmaster(night: date, api_key: str) -> list[dict]:
    start, end = night_window(night)
    events, page = [], 0
    while True:
        data = json.loads(get("https://app.ticketmaster.com/discovery/v2/events.json", {
            "apikey": api_key,
            # music plus the performing arts the site covers (opera, ballet, classical, dance)
            "classificationName": "Music,Classical,Opera,Ballet,Dance",
            "geoPoint": geohash(*CENTER),
            "radius": RADIUS_MILES,
            "unit": "miles",
            "startDateTime": utc_param(start),
            "endDateTime": utc_param(end),
            "size": 200,
            "page": page,
            "sort": "date,asc",
        }))
        for e in data.get("_embedded", {}).get("events", []):
            ev = tm_event(e)
            if ev:
                events.append(ev)
        info = data.get("page", {})
        page += 1
        if page >= info.get("totalPages", 0) or page * 200 >= 1000:  # API cap: size * page < 1000
            break
        time.sleep(0.25)  # stay under 5 requests/second
    return events


def tm_image(images: list) -> str | None:
    wide = [i for i in images or [] if i.get("ratio") == "16_9" and i.get("width", 0) >= 600]
    pick = min(wide, key=lambda i: i["width"]) if wide else (images[0] if images else None)
    return pick.get("url") if pick else None


def tm_event(e: dict) -> dict | None:
    venues = e.get("_embedded", {}).get("venues") or []
    if not venues:
        return None
    v = venues[0]
    loc = v.get("location") or {}
    try:
        lat, lng = float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if e.get("dates", {}).get("status", {}).get("code") in {"cancelled", "canceled", "postponed"}:
        return None
    st = e.get("dates", {}).get("start", {})
    when = parse_iso(st.get("dateTime", "")) if st.get("dateTime") else None
    t = clock(when) if when and not st.get("timeTBA") and not st.get("noSpecificTime") else None
    c = (e.get("classifications") or [{}])[0]
    sub = (c.get("subGenre") or {}).get("name", "") or ""
    gen = (c.get("genre") or {}).get("name", "") or ""
    performers = [a["name"] for a in e.get("_embedded", {}).get("attractions") or [] if a.get("name")]
    title = e.get("name") or (performers[0] if performers else "TBA")
    addr = v.get("address") or {}
    address = ", ".join(x for x in [addr.get("line1"), (v.get("city") or {}).get("name"),
                                    (v.get("state") or {}).get("stateCode")] if x) or None
    pr = (e.get("priceRanges") or [{}])[0]
    return {
        "title": title,
        "performers": performers,
        "venue": v.get("name", ""),
        "address": address,
        "lat": round(lat, 5),
        "lng": round(lng, 5),
        "date": st.get("localDate") or (when.astimezone(NY).date().isoformat() if when else None),
        "time": t,
        "end": None,
        "url": e.get("url"),
        "genre": bucket(sub, gen, title),
        "subgenre": next((x for x in (sub, gen) if x.strip().lower() not in VAGUE), None),
        "price": price_label(pr.get("min"), pr.get("max"), pr.get("currency", "USD")),
        "program": [],
        "description": clean_text(e.get("info") or e.get("description") or e.get("pleaseNote")),
        "image": tm_image(e.get("images") or []),
        "source": "ticketmaster",
    }


# ---------------------------------------------------------------- venue calendars (JSON-LD)

LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
EVENT_TYPES = {"event", "musicevent", "comedyevent", "theaterevent", "danceevent", "festival",
               "socialevent", "educationevent"}


def walk_ld(node):
    """Yield every dict in a JSON-LD blob (handles @graph, lists, nested objects)."""
    if isinstance(node, list):
        for n in node:
            yield from walk_ld(n)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
            if k in node:
                yield from walk_ld(node[k])


def is_event(d: dict) -> bool:
    t = d.get("@type", "")
    types = t if isinstance(t, list) else [t]
    return any(str(x).lower() in EVENT_TYPES for x in types)


def offers_price(offers) -> str | None:
    items = offers if isinstance(offers, list) else [offers]
    vals, cur = [], "USD"
    for o in items:
        if not isinstance(o, dict):
            continue
        cur = o.get("priceCurrency") or cur
        for k in ("price", "lowPrice", "highPrice"):
            try:
                if o.get(k) not in (None, ""):
                    vals.append(float(str(o[k]).replace("$", "").replace(",", "")))
            except ValueError:
                pass
    return price_label(min(vals), max(vals), cur) if vals else None


def from_venue_page(venue: dict, night: date) -> list[dict]:
    page = get(venue["url"])
    start, end = night_window(night)
    out = []
    for blob in LD_RE.findall(page):
        try:
            data = json.loads(html.unescape(blob.strip()))
        except json.JSONDecodeError:
            continue
        for d in walk_ld(data):
            if not is_event(d):
                continue
            raw_start = str(d.get("startDate", ""))
            when = parse_iso(raw_start)
            if not when or not (start <= when < end):
                continue
            status = str(d.get("eventStatus", "")).lower()
            if "cancel" in status or "postpon" in status:
                continue
            loc = d.get("location") if isinstance(d.get("location"), dict) else {}
            geo = loc.get("geo") or {}
            try:
                lat, lng = float(geo["latitude"]), float(geo["longitude"])
            except (KeyError, TypeError, ValueError):
                lat, lng = venue["lat"], venue["lng"]
            raw_end = str(d.get("endDate", ""))
            end_dt = parse_iso(raw_end)
            raw_genre = d.get("genre") or ""
            if isinstance(raw_genre, list):
                raw_genre = ", ".join(map(str, raw_genre))
            performers = names_of(d.get("performer"))
            title = (names_of(d.get("name")) or performers or ["TBA"])[0]
            out.append({
                "title": title,
                "performers": performers,
                "venue": venue["name"],
                "address": address_of(loc.get("address")) or venue.get("address"),
                "lat": round(lat, 5),
                "lng": round(lng, 5),
                "date": when.astimezone(NY).date().isoformat(),
                "time": clock(when) if has_time(raw_start) else None,
                "end": clock(end_dt) if end_dt and has_time(raw_end) and end_dt > when else None,
                "url": d.get("url") if str(d.get("url", "")).startswith("http") else venue["url"],
                "genre": bucket(str(raw_genre), venue.get("genre", "")),
                "subgenre": clean_text(raw_genre, 60),
                "price": offers_price(d.get("offers")),
                "program": names_of(d.get("workPerformed")),
                "description": clean_text(d.get("description")),
                "image": image_of(d.get("image")),
                "source": "venue",
            })
    return out


# ---------------------------------------------------------------- merge + write

STOP = {"live", "with", "presents", "featuring", "night", "tour", "concert", "show", "special", "guest",
        "guests", "evening", "performance", "performs", "plays", "season"}
FILL = ["address", "time", "end", "url", "price", "description", "image", "subgenre", "date"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def tokens(e: dict) -> set[str]:
    text = " ".join([e.get("title") or ""] + list(e.get("performers") or []))
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 3 and t not in STOP}


def same_show(a: dict, b: dict) -> bool:
    """Same venue, same start time (when both known) and overlapping names."""
    if norm(a["venue"])[:10] != norm(b["venue"])[:10]:
        return False
    if a.get("time") and b.get("time") and a["time"] != b["time"]:
        return False
    return norm(a["title"]) == norm(b["title"]) or bool(tokens(a) & tokens(b))


def absorb(into: dict, other: dict) -> None:
    """Fill gaps in one record with another source's details."""
    for f in FILL:
        if not into.get(f) and other.get(f):
            into[f] = other[f]
    if into.get("genre") == "Other" and other.get("genre") != "Other":
        into["genre"] = other["genre"]
    for key in ("performers", "program"):
        for x in other.get(key) or []:
            if x not in into.setdefault(key, []):
                into[key].append(x)
    if other.get("sponsored"):
        into["sponsored"] = True
    if other.get("source") and other["source"] not in into.get("source", ""):
        into["source"] = f"{into.get('source', '')}+{other['source']}".strip("+")


def minutes(t: str | None) -> int:
    if not t:
        return 99999
    h, m = map(int, re.match(r"(\d+):(\d+)", t).groups())
    mins = (h % 12 + (12 if t.endswith("PM") else 0)) * 60 + m
    return mins + 1440 if mins < ROLLOVER_HOUR * 60 else mins


def merge(events: list[dict]) -> list[dict]:
    out: list[dict] = []
    for e in events:
        for o in out:
            if same_show(o, e):
                absorb(o, e)
                break
        else:
            out.append({**e, "performers": list(e.get("performers") or []), "program": list(e.get("program") or [])})
    for e in out:
        e["performers"] = [p for p in e["performers"] if norm(p) != norm(e["title"])]
        e["artist"] = ", ".join(e["performers"][:3]) or e["title"]
    out.sort(key=lambda e: (minutes(e.get("time")), e["venue"]))
    for i, e in enumerate(out, 1):
        e["id"] = i
    return out


def active_placements(path: Path, night: date) -> list[dict]:
    """Paid placements from sponsored.json that run on this night."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        log(f"  sponsored.json is not valid JSON, ignoring it: {e}")
        return []
    day = night.isoformat()
    return [p for p in data.get("placements", [])
            if (not p.get("from") or p["from"] <= day) and (not p.get("until") or day <= p["until"])]


def sponsored_events(placements: list[dict], night: date) -> list[dict]:
    """Shows a sponsor paid to list that the daily sources may not have."""
    out = []
    for p in placements:
        e = p.get("event")
        if not isinstance(e, dict):
            continue
        try:
            lat, lng = float(e["lat"]), float(e["lng"])
        except (KeyError, TypeError, ValueError):
            log(f"  sponsored event skipped (needs lat and lng): {e.get('title')}")
            continue
        ev = {"performers": [], "program": [], "end": None, "address": None, "price": None,
              "description": None, "image": None, "url": None, "subgenre": None, **e}
        ev.update(lat=lat, lng=lng, sponsored=True, source="sponsored", date=e.get("date") or night.isoformat())
        ev["title"] = ev.get("title") or "TBA"
        ev["genre"] = ev.get("genre") if ev.get("genre") in GENRES else bucket(ev.get("genre") or "")
        out.append(ev)
    return out


def mark_sponsored(events: list[dict], placements: list[dict]) -> int:
    """Flag shows matching a placement's venue (and optional title words) as sponsored."""
    count = 0
    for p in placements:
        if p.get("event") or not p.get("venue"):
            continue
        venue, words = norm(p["venue"])[:10], (p.get("title_contains") or "").lower()
        for e in events:
            if norm(e["venue"])[:10] == venue and (not words or words in e["title"].lower()):
                if not e.get("sponsored"):
                    count += 1
                e["sponsored"] = True
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "events.json"))
    ap.add_argument("--date", help="night to build, YYYY-MM-DD (default: current NYC night)")
    ap.add_argument("--venues", default=str(Path(__file__).resolve().parent / "venues.json"))
    ap.add_argument("--sponsored", default=str(ROOT / "sponsored.json"))
    args = ap.parse_args()

    night = date.fromisoformat(args.date) if args.date else current_night()
    log(f"Building lineup for the night of {night.isoformat()}")

    collected: list[dict] = []
    ok_sources, failed_sources = 0, 0

    # venue calendars first: their titles and programs are usually the most descriptive
    venues = json.loads(Path(args.venues).read_text())["venues"]
    for v in venues:
        try:
            found = from_venue_page(v, night)
            log(f"  {v['name']}: {len(found)} events")
            collected += found
            ok_sources += 1
        except Exception as e:  # noqa: BLE001
            log(f"  {v['name']} FAILED: {e}")
            failed_sources += 1

    key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    if key:
        try:
            tm = from_ticketmaster(night, key)
            log(f"  ticketmaster: {len(tm)} events")
            collected += tm
            ok_sources += 1
        except Exception as e:  # noqa: BLE001
            log(f"  ticketmaster FAILED: {e}")
            failed_sources += 1
    else:
        log("  ticketmaster: skipped (no TICKETMASTER_API_KEY)")

    if ok_sources == 0:
        log("Every source failed; keeping the existing events.json.")
        return 1

    placements = active_placements(Path(args.sponsored), night)
    extra = sponsored_events(placements, night)
    events = merge(collected + extra)
    flagged = mark_sponsored(events, placements)
    if placements:
        log(f"  sponsored: {len(placements)} active placement(s), {len(extra)} added show(s), {flagged} matched show(s)")
    payload = {
        "date": night.isoformat(),
        "generated": datetime.now(NY).isoformat(timespec="seconds"),
        "count": len(events),
        "events": events,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    log(f"Wrote {len(events)} events to {args.out} ({failed_sources} source(s) failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
