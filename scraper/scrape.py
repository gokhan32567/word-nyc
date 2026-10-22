#!/usr/bin/env python3
"""Build events.json with tonight's NYC shows.

"Tonight" runs from 5:00 AM today to 5:00 AM tomorrow, New York time, matching the page.

Sources, merged into one lineup:
  1. Venue calendars (venues.json). Each venue page is opened in a headless browser, then read with
     the first method that works:
       a. schema.org event data on the page (JSON-LD)
       b. The Events Calendar for WordPress (public REST API)
       c. an iCal feed linked from the page
       d. Eventbrite organizer feed (needs EVENTBRITE_TOKEN and the venue's organizer id)
       e. AI reading of the page text (needs ANTHROPIC_API_KEY), with every show checked against the page
  2. Ticketmaster Discovery API (needs TICKETMASTER_API_KEY); also covers TicketWeb and Universe venues
  3. Approved rows from the "Submit your show" form (published sheet in SUBMISSIONS_CSV_URL)
  4. Paid placements in sponsored.json

Outputs: events.json (the lineup), coverage.json (what each venue produced), scraper/geocache.json.

Usage:
  python scraper/scrape.py                       # tonight, writes events.json + coverage.json
  python scraper/scrape.py --date 2026-10-31
  python scraper/scrape.py --only "Smalls,Birdland"   # just these venues (for testing)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, NY, ROOT, current_night, log, minutes, norm  # noqa: E402
from genres import GENRES, bucket  # noqa: E402
import feeds  # noqa: E402
import geo  # noqa: E402
import report  # noqa: E402
from shows import is_show, is_strict  # noqa: E402
import tm  # noqa: E402

# Claude Haiku 5.5 list price per million tokens (prompts up to 100K tokens)
AI_PRICE_IN, AI_PRICE_OUT = 0.10, 0.50


# ---------------------------------------------------------------- reading one venue

def read_venue(v: dict, snap, night: date, ai_key: str, eb_token: str) -> tuple[list[dict], dict]:
    """Returns (events, coverage row). Structured data first, AI reading as the fallback."""
    row = {"name": v["name"], "url": v["url"], "read_url": None, "method": None, "status": "error",
           "shows": 0, "detail": None}
    if snap is None:
        row.update(status="skipped", detail="browser not available")
        return [], row
    row["read_url"] = snap.final_url or snap.url
    if snap.error and "robots.txt" in snap.error:
        row.update(status="robots", detail=snap.error)
        return [], row
    page_url = snap.final_url or v["url"]

    attempts = []
    if snap.jsonld:
        attempts.append(("event data", lambda: feeds.jsonld_events(snap.jsonld, v, night, page_url)))
    if snap.tribe or v.get("method") == "tribe":
        attempts.append(("WordPress calendar", lambda: feeds.tribe_events(page_url, v, night)))
    for ics in ([v["ical"]] if v.get("ical") else []) + snap.ical[:1]:
        attempts.append(("iCal", lambda ics=ics: feeds.ical_events(ics, v, night)))
    if v.get("eventbrite") and eb_token:
        attempts.append(("Eventbrite", lambda: feeds.eventbrite_events(v["eventbrite"], eb_token, v, night)))
    strict = is_strict(v)
    for label, fn in attempts:
        try:
            listed = fn()
        except Exception as e:  # noqa: BLE001
            log(f"  {v['name']}: {label} failed ({type(e).__name__}: {str(e)[:100]})")
            continue
        if not listed:
            continue
        found = [e for e in listed if v.get("all_events") or is_show(e["title"], e.pop("_hint", ""), strict)]
        for e in found:
            e.pop("_hint", None)
        dropped = len(listed) - len(found)
        note = f"left out {dropped} non-performance listing{'s' * (dropped != 1)}" if dropped else None
        # The venue's own calendar data covers the whole night, so no need to read the page with AI too.
        row.update(method=label, status="ok" if found else "none-tonight", shows=len(found), detail=note)
        return found, row

    if snap.blocked:
        row.update(status="blocked", detail=f"HTTP {snap.status}" if snap.status else "bot check page")
        return [], row
    if snap.error:
        row.update(status="error", detail=snap.error)
        return [], row
    if not ai_key:
        row.update(status="skipped", detail="no ANTHROPIC_API_KEY")
        return [], row
    import ai
    try:
        found, info = ai.extract(snap, v, night, ai_key)
    except ai.AIError as e:
        row.update(status="error", method="AI", detail=str(e)[:200])
        return [], row
    found = [e for e in found if v.get("all_events") or is_show(e["title"], "", strict)]
    if v.get("_targets"):  # a campus calendar: put each show at its presenter's hall, skip other presenters
        found = [e for e in (assign_presenter(e, v["_targets"]) for e in found) if e]
    for e in found:
        e.pop("_presenter", None)
    row.update(method="AI", status="ok" if found else "none-tonight", shows=len(found),
               detail=(f"{info['page_kind']}; dropped " + ", ".join(f"{n}× {why}" for why, n in info["rejected"].items())
                       if info["rejected"] else info["page_kind"]),
               tokens=[info["input_tokens"], info["output_tokens"]], examples=info.get("examples"))
    return found, row


def safe_read(v: dict, snap, night: date, ai_key: str, eb_token: str) -> tuple[list[dict], dict]:
    """One venue's problem must never stop the whole lineup."""
    try:
        return read_venue(v, snap, night, ai_key, eb_token)
    except Exception as e:  # noqa: BLE001
        log(f"  {v['name']}: FAILED {type(e).__name__}: {str(e)[:160]}")
        return [], {"name": v["name"], "url": v["url"], "read_url": None, "method": None, "status": "error",
                    "shows": 0, "detail": f"{type(e).__name__}: {str(e)[:160]}"}


def assign_presenter(e: dict, targets: dict) -> dict | None:
    who = norm(e.get("_presenter") or "")
    for org, t in targets.items():
        if who and (norm(org) in who or who in norm(org)):
            e.update(venue=t["name"], address=t.get("address"), lat=t["lat"], lng=t["lng"])
            return e
    return None


# ---------------------------------------------------------------- merging sources

STOP = {"live", "with", "presents", "featuring", "night", "tour", "concert", "show", "special", "guest",
        "guests", "evening", "performance", "performs", "plays", "season"}
VENUE_NOISE = re.compile(r"\b(the|jazz|club|nyc|new york|theat(er|re)|hall|bar|music|room|lounge|cafe|café|"
                         r"brooklyn|manhattan|at|and|presents|powered by \w+)\b", re.I)
FILL = ["address", "time", "end", "price", "description", "image", "subgenre", "date", "listing_url"]


def tokens(e: dict) -> set[str]:
    text = " ".join([e.get("title") or ""] + list(e.get("performers") or []))
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 3 and t not in STOP}


def venue_key(name: str) -> str:
    return norm(VENUE_NOISE.sub(" ", name or ""))


def same_venue(a: dict, b: dict) -> bool:
    ka, kb = venue_key(a["venue"]), venue_key(b["venue"])
    if ka and kb and len(min(ka, kb, key=len)) >= 4 and (ka in kb or kb in ka):
        return True
    try:
        return geo.distance_m((a["lat"], a["lng"]), (b["lat"], b["lng"])) <= 60
    except (KeyError, TypeError):
        return False


def same_show(a: dict, b: dict) -> bool:
    """Same venue and overlapping names, at the same start time (when both known).

    Exception: one listing's title containing the other's ("X" vs "Promoter Presents X") within
    90 minutes is one show listed twice. Identical titles at different times are separate sets.
    """
    if not same_venue(a, b):
        return False
    ta, tb = norm(a["title"]), norm(b["title"])
    if a.get("time") and b.get("time") and a["time"] != b["time"]:
        nested = ta != tb and min(len(ta), len(tb)) >= 6 and (ta in tb or tb in ta)
        return nested and abs(minutes(a["time"]) - minutes(b["time"])) <= 90
    return ta == tb or bool(tokens(a) & tokens(b))


def absorb(into: dict, other: dict) -> None:
    """Fill gaps in one record with another source's details."""
    for f in FILL:
        if not into.get(f) and other.get(f):
            into[f] = other[f]
    # a Ticketmaster link is where the tickets are actually sold (and can earn a commission)
    if other.get("source") == "ticketmaster" and other.get("url"):
        into["url"] = other["url"]
    elif not into.get("url"):
        into["url"] = other.get("url")
    if into.get("genre") == "Other" and other.get("genre") != "Other":
        into["genre"] = other["genre"]
    for key in ("performers", "program"):
        for x in other.get(key) or []:
            if norm(x) not in {norm(y) for y in into.setdefault(key, [])}:
                into[key].append(x)
    if other.get("sponsored"):
        into["sponsored"] = True
    if other.get("source") and other["source"] not in into.get("source", ""):
        into["source"] = f"{into.get('source', '')}+{other['source']}".strip("+")


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


# ---------------------------------------------------------------- sponsored placements

def active_placements(path: Path, night: date) -> list[dict]:
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
    count = 0
    for p in placements:
        if p.get("event") or not p.get("venue"):
            continue
        key, words = venue_key(p["venue"]), (p.get("title_contains") or "").lower()
        for e in events:
            if key and venue_key(e["venue"]) == key and (not words or words in e["title"].lower()):
                count += 0 if e.get("sponsored") else 1
                e["sponsored"] = True
    return count


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "events.json"))
    ap.add_argument("--coverage", default=str(ROOT / "coverage.json"))
    ap.add_argument("--date", help="night to build, YYYY-MM-DD (default: current NYC night)")
    ap.add_argument("--venues", default=str(HERE / "venues.json"))
    ap.add_argument("--sponsored", default=str(ROOT / "sponsored.json"))
    ap.add_argument("--only", default=os.environ.get("VENUE_FILTER", ""), help="comma-separated text; read only venues whose name contains one of them")
    ap.add_argument("--no-browser", action="store_true", help="skip venue pages (Ticketmaster etc. only)")
    args = ap.parse_args()

    night = date.fromisoformat(args.date) if args.date else current_night()
    log(f"Building lineup for the night of {night.isoformat()}")
    ai_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    eb_token = os.environ.get("EVENTBRITE_TOKEN", "").strip()
    geocoder = geo.Geocoder()

    venues = json.loads(Path(args.venues).read_text())["venues"]
    if args.only.strip():
        wanted = {norm(x) for x in args.only.split(",") if x.strip()}
        venues = [v for v in venues if any(w in norm(v["name"]) for w in wanted)]
    placed = geo.place_venues([dict(v) for v in venues], geocoder)
    by_name = {p["name"]: p for p in placed}
    everyone = by_name
    if any(p.get("presenters") for p in placed) and args.only.strip():  # targets may be outside the --only filter
        everyone = {p["name"]: p for p in geo.place_venues(
            [dict(x) for x in json.loads(Path(args.venues).read_text())["venues"]], geocoder)}
    for p in placed:
        if p.get("presenters"):
            p["_targets"] = {org: {k: everyone[name][k] for k in ("name", "address", "lat", "lng")}
                             for org, name in p["presenters"].items() if name in everyone}
    rows = [{"name": v["name"], "url": v["url"], "status": "no-location", "shows": 0,
             "detail": v.get("address")} for v in venues if v["name"] not in {p["name"] for p in placed}]

    collected: list[dict] = []
    ok_sources = 0
    rows += [{"name": p["name"], "url": p["url"], "status": "skipped", "shows": 0,
              "detail": f"site can't be read; shows come from the {p['via']} calendar"} for p in placed if p.get("via")]
    placed = [p for p in placed if not p.get("via")]

    # 1. venue calendars
    if placed and not args.no_browser:
        import browse
        log(f"  reading {len(placed)} venue pages in the browser…")
        snaps = browse.snapshot_all(placed, night)
        results: list[tuple[list[dict], dict]] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda v: safe_read(v, snaps.get(v["name"]), night, ai_key, eb_token), placed))
        for (found, row), v in zip(results, placed):
            log(f"  {v['name']}: {row['status']} {row['shows']} {row.get('method') or ''} {row.get('detail') or ''}".rstrip())
            collected += found
            rows.append(row)
        ok_sources += sum(1 for _, r in results if r["status"] in ("ok", "none-tonight"))
        if args.only.strip():  # test runs: keep what the browser saw (published to the "debug" branch)
            with open(ROOT / "debug.txt", "w") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                for v in placed:
                    sn = snaps.get(v["name"])
                    if sn:
                        f.write(f"\n### {v['name']}\n{sn.final_url} (HTTP {sn.status}, {len(sn.text)} chars)\n"
                                f"followed: {sn.followed}\ntried: {sn.tried}\n"
                                f"links: {[(l['text'][:30], l['href']) for l in sn.first_links[:60]]}\n\n"
                                f"```\n{sn.text[:12000]}\n```\n")
        if not ai_key:
            log("  AI reading skipped: add ANTHROPIC_API_KEY to read venue pages without structured data")

    # 2. Ticketmaster
    key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    if key:
        try:
            found = [e for e in tm.from_ticketmaster(night, key) if is_show(e["title"])]
            log(f"  ticketmaster: {len(found)} events")
            collected += found
            ok_sources += 1
        except Exception as e:  # noqa: BLE001
            log(f"  ticketmaster FAILED: {e}")
    else:
        log("  ticketmaster: skipped (no TICKETMASTER_API_KEY)")

    # 3. form submissions
    csv_url = os.environ.get("SUBMISSIONS_CSV_URL", "").strip()
    if csv_url:
        try:
            found = feeds.submission_events(csv_url, night, geocoder)
            log(f"  submissions: {len(found)} approved for tonight")
            collected += found
        except Exception as e:  # noqa: BLE001
            log(f"  submissions FAILED: {e}")

    # venues that have music every night: an empty result there is almost certainly a reading problem
    nightly = [v["name"] for v in venues if v.get("nightly")]
    have = {e["venue"] for e in collected}
    nightly_missing = [n for n in nightly if n not in have]
    if nightly_missing:
        log(f"  CHECK: no shows found at nightly venues: {', '.join(nightly_missing)}")
    geocoder.save()
    calls = [r["tokens"] for r in rows if r.get("tokens")]
    tin, tout = sum(c[0] for c in calls), sum(c[1] for c in calls)
    ai_usage = {"nightly_missing": nightly_missing, "calls": len(calls), "input_tokens": tin, "output_tokens": tout,
                "cost_usd": round(tin / 1e6 * AI_PRICE_IN + tout / 1e6 * AI_PRICE_OUT, 4)}

    if not collected:
        report.write(night, rows, [], ai_usage, Path(args.coverage))
        log("No shows found tonight; keeping the existing events.json. See coverage.json for each venue.")
        return 1

    # 4. sponsored placements, then merge everything
    placements = active_placements(Path(args.sponsored), night)
    extra = sponsored_events(placements, night)
    # A re-run later the same night only adds: venue pages drop shows once they've started, so keep
    # what an earlier run of this night already found.
    earlier = []
    try:
        prev = json.loads(Path(args.out).read_text())
        if prev.get("date") == night.isoformat() and not args.only.strip():
            earlier = [{k: v for k, v in e.items() if k not in ("id", "artist", "sponsored")} for e in prev["events"]]
    except (OSError, ValueError, KeyError):
        pass
    events = merge(collected + extra + earlier)
    flagged = mark_sponsored(events, placements)
    if placements:
        log(f"  sponsored: {len(placements)} active placement(s), {len(extra)} added, {flagged} matched")
    for e in events:
        e.pop("tokens", None)

    Path(args.out).write_text(json.dumps({
        "date": night.isoformat(),
        "generated": datetime.now(NY).isoformat(timespec="seconds"),
        "count": len(events),
        "events": events,
    }, ensure_ascii=False, indent=2) + "\n")
    report.write(night, rows, events, ai_usage, Path(args.coverage))
    log(f"Wrote {len(events)} shows to {args.out}; AI cost about ${ai_usage['cost_usd']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
