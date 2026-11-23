"""Event guides: pages that list tonight's events at many venues (e.g. ClubFreeTime's free events).

One AI call per guide reads the page and returns each live-music event with its venue and address.
Events at venues we already read keep the venue's own listing when that page read fine; events at
venues we don't know are placed on the map from their street address.
"""
from __future__ import annotations

import os
import re
from datetime import date

from common import ROOT, log, norm

# Each guide: name, url, note for the reader, optional price for every event on it.
# Not usable (Nov 2026): ClubFreeTime hides each event's venue and address behind a paid membership,
# so its listings can't be placed on the map.
GUIDES: list[dict] = []

GUIDE_TOOL = {
    "name": "report_guide_events",
    "description": "Report the live music events this guide lists for the given night.",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "the event's name as listed"},
                    "performers": {"type": "array", "items": {"type": "string"}},
                    "venue": {"type": "string", "description": "the venue's name as listed"},
                    "address": {"type": "string", "description": "street address with city, as listed ('' if none)"},
                    "time": {"type": "string", "description": "start time like '7:30 PM' ('' if none)"},
                    "url": {"type": "string", "description": "the event's link on the page ('' if none)"},
                    "kind": {"type": "string", "enum": ["concert", "dj", "other"],
                             "description": "concert = live music performance (incl. jazz, classical, open mic music); "
                                            "dj = a DJ set or dance party; other = anything else (talks, tours, "
                                            "film, comedy, theater, classes, markets, exhibits, kids' activities)"},
                },
                "required": ["title", "venue", "address", "time", "url", "kind"],
            }},
        },
        "required": ["events"],
    },
}


def _match(name: str, known: dict[str, dict]) -> dict | None:
    n = norm(name)
    if not n:
        return None
    if n in known:
        return known[n]
    for k, v in known.items():
        if len(k) >= 6 and len(n) >= 6 and (k in n or n in k):
            return v
    return None


def guide_events(venues: list[dict], rows: list[dict], night: date, ai_key: str, geocoder) -> tuple[list[dict], list[dict]]:
    """Returns (events, coverage rows) for tonight from the event guides."""
    import ai
    import browse
    from feeds import base_event
    from genres import bucket

    known = {norm(v["name"]): v for v in venues}
    read_ok = {r["name"] for r in rows if r.get("status") == "ok"}
    snaps = browse.snapshot_all([dict(g, no_follow=True) for g in GUIDES], night)
    events, out_rows = [], []
    for g in GUIDES:
        snap = snaps.get(g["name"])
        row = {"name": f"{g['name']} (guide)", "url": g["url"], "method": "guide", "shows": 0}
        if not snap or not snap.ok:
            row.update(status="error", detail=(snap.error if snap else "not loaded") or "page unreadable")
            out_rows.append(row)
            continue
        if os.environ.get("VENUE_FILTER"):  # test runs: keep what the guide page showed (debug branch)
            with open(ROOT / "debug.txt", "a") as f:
                f.write(f"\n### {g['name']}\n{snap.final_url} (HTTP {snap.status}, {len(snap.text)} chars)\n"
                        f"```\n{snap.text[:20000]}\n```\n")
        links = "\n".join(f"{l['text'][:80]} -> {l['href']}" for l in snap.links[:400] if l.get("text"))
        prompt = (f"{g['note']}\nNight to report: {night:%A, %B %-d, %Y}. {ai.loaded_note(night)}\n"
                  f"List only events on that night at a physical place in New York City or the New Jersey towns "
                  f"across the Hudson. Copy venue names, addresses and times exactly as listed; never guess them.\n\n"
                  f"PAGE TEXT ({snap.final_url}):\n{snap.text[:60_000]}\n\nLINKS:\n{links[:15_000]}")
        try:
            got, usage = ai.call_claude(ai_key, prompt, max_tokens=4000, tool=GUIDE_TOOL,
                                        ask="Report the music events with report_guide_events.")
        except ai.AIError as e:
            row.update(status="error", detail=str(e)[:200])
            out_rows.append(row)
            continue
        kept, skipped = [], {"not music": 0, "venue read itself": 0, "no time": 0, "no location": 0}
        for e in got.get("events") or []:
            if e.get("kind") not in ("concert", "dj"):
                skipped["not music"] += 1
                continue
            t = (e.get("time") or "").strip().upper().replace(".", "")
            if not re.fullmatch(r"\d{1,2}(:\d{2})? ?[AP]M", t):
                skipped["no time"] += 1
                continue
            t = re.sub(r"^(\d{1,2}) ?([AP]M)$", r"\1:00 \2", t).replace("AM", " AM").replace("PM", " PM")
            t = re.sub(r"\s+", " ", t).strip()
            v = _match(e.get("venue", ""), known)
            if v and v["name"] in read_ok:
                skipped["venue read itself"] += 1  # the venue's own page is the better source
                continue
            if not v:
                addr = (e.get("address") or "").strip()
                if not re.search(r"\d", addr):
                    skipped["no location"] += 1
                    continue
                loc = geocoder(addr)
                if not loc:
                    skipped["no location"] += 1
                    continue
                v = {"name": e["venue"].strip()[:80], "address": addr, "lat": loc[0], "lng": loc[1],
                     "url": e.get("url") or g["url"], "genre": "Other"}
            url = e.get("url") if str(e.get("url", "")).startswith("http") else g["url"]
            kept.append(base_event(
                v, title=e["title"].strip()[:140], performers=[p for p in e.get("performers") or [] if p][:8],
                date=night.isoformat(), time=t, url=url,
                genre=bucket(e["title"], "Electronic" if e["kind"] == "dj" else "", v.get("genre", "")) or "Other",
                price=g.get("price"), source=f"guide-{norm(g['name'])}", listing_url=g["url"]))
        events += kept
        row.update(status="ok" if kept else "none-tonight", shows=len(kept),
                   detail=", ".join(f"{n} {k}" for k, n in skipped.items() if n) or None,
                   tokens=[usage["input_tokens"], usage["output_tokens"]],
                   examples=[f"{x['time']} {x['venue']}: {x['title']}" for x in kept[:5]])
        out_rows.append(row)
        log(f"  {g['name']} guide: {len(kept)} music events kept ({row['detail'] or 'nothing skipped'})")
    return events, out_rows
