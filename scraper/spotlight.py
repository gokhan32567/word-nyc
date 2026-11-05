#!/usr/bin/env python3
"""One-show "spotlight" notifications in the afternoon, on top of the noon "Tonight's picks".

  afternoon  3 PM every day: one show starting later this evening
  evening    5 PM Fridays and Saturdays: one more show, from the later part of the night

Each picks a show still ahead (starting at least an hour later), from a different venue than the noon picks
and any earlier spotlight today, preferring well-known rooms, with a little variety from day to day. Tapping
it opens that show on the map. Sponsored shows are never used here (they lead the noon push instead).
spotlight-log.json records what went out so each slot sends at most once a day.

  ONESIGNAL_API_KEY=... python scraper/spotlight.py afternoon      # send (once, inside its time window)
  python scraper/spotlight.py evening --dry-run                     # print it, send nothing
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, NY, ROOT, minutes  # noqa: E402
from notify import api, line, nice, payload, pick, short_venue, show_key  # noqa: E402

LOG = ROOT / "spotlight-log.json"
SLOTS = {  # window it may send in (NY time, minutes after midnight), days (Mon=0), earliest show start
    "afternoon": {"window": (14 * 60 + 30, 16 * 60 + 30), "days": range(7), "earliest": 18 * 60, "label": "3pm"},
    "evening": {"window": (16 * 60 + 30, 18 * 60 + 30), "days": (4, 5), "earliest": 19 * 60, "label": "5pm"},
}
STAR = {"Carnegie Hall", "David Geffen Hall", "Metropolitan Opera House", "David H. Koch Theater", "Roulette",
        "The Stone", "National Sawdust", "Le Poisson Rouge", "Jazz at Lincoln Center", "Dizzy's Club", "BAM",
        "Chamber Music Society of Lincoln Center", "Brooklyn Steel", "Webster Hall", "Bowery Ballroom", "Barbès",
        "Bar Bayeux", "The Jazz Gallery", "Birdland", "Joe's Pub", "54 Below", "Elsewhere", "Union Pool", "Pianos"}


def choose(events: list[dict], venues: list[dict], slot: str, now_min: int, used_venues: set[str], day: str) -> dict | None:
    cfg = SLOTS[slot]
    nightly = {v["name"] for v in venues if v.get("nightly")}
    start_after = max(cfg["earliest"], now_min + 60)
    cands = [e for e in events if not e.get("sponsored") and e["venue"] not in used_venues
             and start_after <= minutes(e.get("time")) <= 24 * 60 + 30 and len(e.get("title") or "") >= 4]
    if not cands:
        return None
    def score(e):
        s = 0
        s += 3 if e["venue"] in STAR else 0
        s += 2 if e["venue"] in nightly else 0
        s += 1 if e.get("description") else 0
        s += 1 if e.get("performers") else 0
        return s
    best = sorted(cands, key=lambda e: (-score(e), minutes(e.get("time"))))[:8]
    return random.Random(f"{day}-{slot}").choice(best)  # varied, but the same answer if re-run that day


def compose(e: dict, slot: str) -> tuple[str, str]:
    t = (e.get("time") or "").replace(":00", "")
    title = ("Tonight: " if slot == "afternoon" else "Later tonight: ") + nice(e["title"])
    if len(title) > 60:
        title = title[:59].rstrip() + "…"
    extra = (e.get("description") or "").strip()
    if not extra:
        extra = e.get("genre") or ""
    body = f"{short_venue(e['venue'])}, {t}." + (f" {extra}" if extra else "")
    if len(body) > 200:
        body = body[:199].rsplit(" ", 1)[0] + "…"
    return title, body + " Tap to see it on the map."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slot", choices=sorted(SLOTS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="send even outside the time window or if already sent")
    args = ap.parse_args()
    cfg = SLOTS[args.slot]

    now = datetime.now(NY)
    today, now_min = now.date().isoformat(), now.hour * 60 + now.minute
    data = json.loads((ROOT / "events.json").read_text())
    if args.dry_run:
        today = data.get("date") or today
    if not args.force and not args.dry_run:
        if now.weekday() not in cfg["days"]:
            print(f"No {args.slot} spotlight on {now:%A}.")
            return 0
        if not cfg["window"][0] <= now_min <= cfg["window"][1]:
            print(f"Outside the {args.slot} window ({now:%H:%M}); not sending.")
            return 0
    if not args.dry_run and data.get("date") != today:
        print(f"::warning::Lineup is for {data.get('date')}, not today ({today}); not sending.")
        return 0
    log = json.loads(LOG.read_text()) if LOG.exists() else {}
    day_log = log.get(today, {})
    if args.slot in day_log and not args.force and not args.dry_run:
        print(f"Today's {args.slot} spotlight already went out.")
        return 0

    venues = json.loads((HERE / "venues.json").read_text())["venues"]
    events = data["events"]
    used = {e["venue"] for e in pick(events, venues)}            # today's noon picks
    used |= {s.get("venue") for s in day_log.values()}            # earlier spotlights today
    e = choose(events, venues, args.slot, 0 if args.dry_run else now_min, used, today)
    if not e:
        print("No suitable show still ahead; nothing sent.")
        return 0
    title, body = compose(e, args.slot)
    path = f"/?show={urllib.parse.quote(show_key(e))}&source=spotlight-{cfg['label']}"
    print(f"{title}\n  {body}\n  opens {path}")
    if args.dry_run:
        return 0
    key = os.environ.get("ONESIGNAL_API_KEY", "").strip()
    if not key:
        print("No ONESIGNAL_API_KEY; not sending.")
        return 1
    result = api("POST", "/notifications", key, payload(title, body, path, {"included_segments": ["Total Subscriptions"]}))
    print("OneSignal:", result)
    day_log[args.slot] = {"id": result.get("id"), "venue": e["venue"], "title": e["title"], "time": e.get("time")}
    log[today] = day_log
    LOG.write_text(json.dumps(dict(sorted(log.items())[-40:]), indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
