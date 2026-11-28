#!/usr/bin/env python3
"""Weekly venue discovery: find NYC music venues that aren't on our list yet, test them, add the good ones.

1. Read listing sites (jazz-nyc.com, Songkick's NYC calendar, Eventbrite's NYC music search, ...) and collect
   every venue they name.
2. Drop the ones we already know (venues.json, venues seen before, Ticketmaster venues).
3. For each new venue: open its website (or its listing page), find its street address and an upcoming
   calendar, and check it has dated music shows in the next three weeks.
4. Venues that pass are added to venues.json; the rest go in the report with the reason.
Writes discover.md and discover.json (remembers venues already tested so they're re-checked only every 8 weeks).
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ai  # noqa: E402
import browse  # noqa: E402
import geo  # noqa: E402
from common import ROOT, log, norm  # noqa: E402
from genres import GENRES  # noqa: E402

HERE = Path(__file__).resolve().parent
VENUES = HERE / "venues.json"
STATE = ROOT / "discover.json"
REPORT = ROOT / "discover.md"
MAX_TESTS = 25          # new venues tested per run
MAX_ADDS = 12           # venues added per run
RETEST_DAYS = 56

SOURCES = [
    {"name": "Songkick NYC", "url": "https://www.songkick.com/metro-areas/7644-us-new-york-nyc"},
    {"name": "Songkick NYC p2", "url": "https://www.songkick.com/metro-areas/7644-us-new-york-nyc?page=2"},
    {"name": "Songkick NYC p3", "url": "https://www.songkick.com/metro-areas/7644-us-new-york-nyc?page=3"},
    {"name": "DoNYC today", "url": "https://donyc.com/events/today"},
    {"name": "DoNYC tomorrow", "url": "https://donyc.com/events/tomorrow"},
    {"name": "Oh My Rockness", "url": "https://www.ohmyrockness.com/shows"},
]

VENUES_TOOL = {
    "name": "report_venues",
    "description": "Report every distinct venue (place) this page names for upcoming events.",
    "input_schema": {"type": "object", "properties": {"venues": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "venue name exactly as listed"},
            "area": {"type": "string", "description": "borough/town/area as listed ('' if none)"},
            "address": {"type": "string", "description": "street address if the page shows it, else ''"},
            "website": {"type": "string", "description": "the venue's own link on the page ('' if none)"},
            "music": {"type": "boolean", "description": "true if the events listed there are live music or DJ nights"},
        },
        "required": ["name", "area", "address", "website", "music"]}}},
        "required": ["venues"]},
}

CHECK_TOOL = {
    "name": "report_venue_check",
    "description": "Report what this venue website shows.",
    "input_schema": {"type": "object", "properties": {
        "is_this_venue": {"type": "boolean", "description": "the page belongs to the named venue (its own site or "
                                                            "its own listing page on a ticketing site)"},
        "address": {"type": "string", "description": "the venue's street address with city, exactly as shown; '' if not shown"},
        "kind": {"type": "string", "enum": ["music venue", "bar or restaurant with live music", "club",
                                            "church or hall", "not a music venue", "closed"]},
        "genre": {"type": "string", "enum": GENRES},
        "calendar_url": {"type": "string", "description": "link to the page listing upcoming dated shows ('' if none)"},
        "upcoming": {"type": "array", "description": "dated music events shown (up to 10)", "items": {
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"},
                           "time": {"type": "string", "description": "start time as shown ('' if none)"},
                           "title": {"type": "string"}},
            "required": ["date", "time", "title"]}},
    }, "required": ["is_this_venue", "address", "kind", "genre", "calendar_url", "upcoming"]},
}

NOISE = re.compile(r"\b(the|nyc|new york|brooklyn|queens|bronx|manhattan|bar|club|lounge|room|hall|"
                   r"music|jazz|cafe|café|restaurant|and|at|venue)\b", re.I)
# areas outside what we cover (the map check catches the rest)
OUTSIDE = re.compile(r"^(li|wt|ct|pa)$|long island(?! city)|westchester|connecticut|philadelphia|newark|asbury|"
                     r"montclair|morristown|princeton|new brunswick|yonkers|white plains|nassau|suffolk|"
                     r"hudson valley|upstate", re.I)


def key(name: str) -> str:
    return norm(NOISE.sub(" ", name or "")) or norm(name)


def known_keys() -> set[str]:
    names = [v["name"] for v in json.loads(VENUES.read_text())["venues"]]
    try:
        names += list(json.loads((HERE / "seen_venues.json").read_text()))
    except (OSError, ValueError):
        pass
    try:
        names += [e["venue"] for e in json.loads((ROOT / "events.json").read_text())["events"]]
    except (OSError, ValueError, KeyError):
        pass
    return {key(n) for n in names if key(n)}


def is_known(name: str, known: set[str]) -> bool:
    k = key(name)
    if not k:
        return True
    return k in known or any(len(k) >= 5 and len(x) >= 5 and (k in x or x in k) for x in known)


def collect(api_key: str, today: date) -> list[dict]:
    snaps = browse.snapshot_all([dict(s, no_follow=True) for s in SOURCES], today)
    import time
    for attempt in range(2):
        thin = [s for s in SOURCES if not snaps.get(s["name"])
                or (len(snaps[s["name"]].text) < 1000 and not snaps[s["name"]].blocked)]
        if not thin:
            break
        time.sleep(20)
        snaps.update(browse.snapshot_all([dict(s, no_follow=True) for s in thin], today, timeout_ms=60000))
    found: dict[str, dict] = {}
    for s in SOURCES:
        snap = snaps.get(s["name"])
        if not snap or not snap.ok:
            log(f"  source {s['name']}: unreadable ({(snap.error if snap else 'not loaded') or 'empty'})")
            continue
        links = "\n".join(f"{l['text'][:80]} -> {l['href']}" for l in snap.links[:600] if l.get("text"))
        prompt = (f"{s.get('note', 'An events listing page for New York City.')}\n\n"
                  f"PAGE TEXT ({snap.final_url}):\n{snap.text[:60_000]}\n\nLINKS:\n{links[:20_000]}")
        try:
            got, _ = ai.call_claude(api_key, prompt, max_tokens=6000, tool=VENUES_TOOL,
                                    ask="List the venues with report_venues.")
        except ai.AIError as e:
            log(f"  source {s['name']}: AI error {str(e)[:120]}")
            continue
        n, listed = 0, got.get("venues") or []
        for v in listed:
            name = (v.get("name") or "").strip()
            if not name or not v.get("music") or OUTSIDE.search((v.get("area") or "").strip()):
                continue
            k = key(name)
            if k and k not in found:
                found[k] = {"name": name[:80], "area": v.get("area", ""), "address": v.get("address", ""),
                            "website": v.get("website", ""), "source": s["name"]}
                n += 1
        log(f"  source {s['name']}: {len(listed)} venues listed, {n} kept")
    return list(found.values())


def test(cands: list[dict], api_key: str, today: date, geocoder) -> tuple[list[dict], list[dict]]:
    """Returns (venues to add, rejected with reasons)."""
    with_site = [c for c in cands if str(c.get("website", "")).startswith("http")]
    snaps = browse.snapshot_all([{"name": c["name"], "url": c["website"]} for c in with_site], today)
    adds, rejected = [], []
    for c in cands:
        snap = snaps.get(c["name"])
        if not snap or not snap.ok:
            rejected.append({**c, "why": "no readable website" if c.get("website") else "no website link"})
            continue
        if "eventbrite." in snap.final_url and "/o/" not in snap.final_url:
            rejected.append({**c, "why": "only an Eventbrite event link, no venue calendar to read"})
            continue
        links = "\n".join(f"{l['text'][:60]} -> {l['href']}" for l in snap.links[:300] if l.get("text"))
        prompt = (f"Venue: {c['name']} ({c.get('area') or 'New York area'}). Today is {today:%A, %B %-d, %Y}.\n"
                  f"Report its street address, what kind of place it is, its calendar page, and the dated music "
                  f"events it shows from today on. Copy dates, times and addresses only as shown; never guess.\n\n"
                  f"PAGE ({snap.final_url}):\n{snap.text[:40_000]}\n\nLINKS:\n{links[:8_000]}")
        try:
            got, _ = ai.call_claude(api_key, prompt, max_tokens=2000, tool=CHECK_TOOL,
                                    ask="Answer with report_venue_check.")
        except ai.AIError as e:
            rejected.append({**c, "why": f"AI error {str(e)[:80]}"})
            continue
        horizon = (today + timedelta(days=21)).isoformat()
        upcoming = [u for u in got.get("upcoming") or []
                    if today.isoformat() <= str(u.get("date", "")) <= horizon and re.search(r"\d", u.get("time") or "")]
        addr = (got.get("address") or c.get("address") or "").strip()
        why = None
        if not got.get("is_this_venue"):
            why = "website isn't this venue's"
        elif got.get("kind") in ("not a music venue", "closed"):
            why = got["kind"]
        elif not re.search(r"\d", addr):
            why = "no street address shown"
        elif len(upcoming) < 2:
            why = f"only {len(upcoming)} dated show(s) with times in the next 3 weeks"
        loc = None if why else geocoder(addr)
        if not why and not loc:
            why = f"address not found on the map ({addr})"
        if not why and not geo.in_nyc(*loc):
            why = "outside the area we cover"
        if not why and re.search(r",\s*NJ\b|New Jersey", addr):
            from areas import NJ_TOWNS, zip_of
            if zip_of(addr) not in NJ_TOWNS:
                why = "New Jersey town outside the ones we cover"
        if why:
            rejected.append({**c, "why": why, "address": addr})
            continue
        cal = got.get("calendar_url") or ""
        url = cal if cal.startswith("http") else snap.final_url
        adds.append({"name": c["name"], "address": addr, "url": url, "genre": got.get("genre") or "Other",
                     "note": f"Added by the weekly discovery job (found on {c['source']}).",
                     "_examples": [f"{u['date']} {u['time']} {u['title']}" for u in upcoming[:3]]})
    return adds[:MAX_ADDS], rejected


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log("no ANTHROPIC_API_KEY")
        return 1
    today = date.today()
    try:
        state = json.loads(STATE.read_text())
    except (OSError, ValueError):
        state = {"tested": {}}
    known = known_keys()
    cands = [c for c in collect(api_key, today) if not is_known(c["name"], known)]
    fresh = [c for c in cands
             if (today - date.fromisoformat(state["tested"].get(key(c["name"]), "2000-01-01"))).days >= RETEST_DAYS]
    log(f"  {len(cands)} venues not on our list; {len(fresh)} not tested in the last 8 weeks")
    fresh = fresh[:MAX_TESTS]
    geocoder = geo.Geocoder()
    adds, rejected = test(fresh, api_key, today, geocoder)
    geocoder.save()
    for c in fresh:
        state["tested"][key(c["name"])] = today.isoformat()

    if adds:
        data = json.loads(VENUES.read_text())
        names = {v["name"] for v in data["venues"]}
        for a in adds:
            if a["name"] not in names:
                data["venues"].append({k: v for k, v in a.items() if not k.startswith("_")})
        VENUES.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")

    lines = [f"# Venue discovery, {today:%b %-d, %Y}", "",
             f"Checked {len(SOURCES)} listing sites; {len(cands)} venues weren't on our list, "
             f"{len(fresh)} were tested this week.", ""]
    lines += [f"## Added ({len(adds)})", ""] + (
        [f"- **{a['name']}**, {a['address']} ({a['genre']}): {'; '.join(a['_examples'])}" for a in adds] or ["- none"])
    lines += ["", f"## Not added ({len(rejected)})", ""] + (
        [f"- {r['name']} ({r.get('area') or '?'}, from {r['source']}): {r['why']}" for r in rejected] or ["- none"])
    REPORT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
