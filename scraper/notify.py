#!/usr/bin/env python3
"""Send the daily "Tonight's picks" push notification through OneSignal.

Picks a few evening shows from events.json (sponsored first, then the big-name rooms), sends one
notification to every subscriber, and records the date in push-log.json so it never goes out twice.

  ONESIGNAL_API_KEY=... python scraper/notify.py           # send today's (once)
  python scraper/notify.py --dry-run                        # just print the message
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, NY, ROOT, minutes  # noqa: E402

APP_ID = "d9f2eefb-d834-4054-92cc-422321667627"
LOG = ROOT / "push-log.json"


def short_venue(name: str) -> str:
    for a, b in (("Village Vanguard", "the Vanguard"), ("Smalls Jazz Club", "Smalls"), ("Blue Note Jazz Club", "Blue Note"),
                 ("Smoke Jazz Club", "Smoke"), ("The Metropolitan Opera House", "the Met"),
                 ("Metropolitan Opera House", "the Met"), ("David Geffen Hall", "Geffen Hall")):
        if name == a:
            return b
    return name


def pick(events: list[dict], venues: list[dict], n: int = 3) -> list[dict]:
    star = {v["name"] for v in venues if v.get("nightly")} | {
        "Carnegie Hall", "David Geffen Hall", "Metropolitan Opera House", "David H. Koch Theater", "Roulette",
        "The Stone", "National Sawdust", "Le Poisson Rouge", "Jazz at Lincoln Center", "Dizzy's Club", "BAM",
        "Chamber Music Society of Lincoln Center", "Brooklyn Steel", "Webster Hall", "Bowery Ballroom"}
    evening = [e for e in events if 17 * 60 <= minutes(e.get("time")) <= 23 * 60 + 30]
    ranked = sorted(evening, key=lambda e: (not e.get("sponsored"), e["venue"] not in star,
                                            abs(minutes(e.get("time")) - 20 * 60), e["venue"]))
    out, seen = [], set()
    for e in ranked:  # one show per venue
        if e["venue"] in seen:
            continue
        seen.add(e["venue"])
        out.append(e)
        if len(out) == n:
            break
    return out


def message(data: dict, venues: list[dict]) -> tuple[str, str]:
    events = data["events"]
    picks = pick(events, venues)
    title = f"Tonight in NYC: {len(events)} shows"
    def nice(t: str) -> str:
        return t.title() if t.isupper() else t
    lines = [f"{nice(e['title'])[:42].strip()} at {short_venue(e['venue'])}, {e['time'].replace(':00', '')}" for e in picks]
    body = " · ".join(lines) + ". Tap for the map."
    return title, body[:230]


def send(title: str, body: str, api_key: str) -> dict:
    req = urllib.request.Request(
        "https://api.onesignal.com/notifications",
        data=json.dumps({
            "app_id": APP_ID, "target_channel": "push", "included_segments": ["Total Subscriptions"],
            "headings": {"en": title}, "contents": {"en": body},
            "url": "https://word-nyc.com/?source=noon", "chrome_web_icon": "https://word-nyc.com/icons/icon-192.png",
            "ttl": 6 * 3600,
        }).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Key {api_key}"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="send even if today's already went out")
    args = ap.parse_args()

    today = datetime.now(NY).date().isoformat()
    data = json.loads((ROOT / "events.json").read_text())
    if data.get("date") != today:
        print(f"Lineup is for {data.get('date')}, not today ({today}); not sending.")
        return 1
    log = json.loads(LOG.read_text()) if LOG.exists() else {}
    if log.get("last") == today and not args.force and not args.dry_run:
        print(f"Already sent today ({today}).")
        return 0
    venues = json.loads((HERE / "venues.json").read_text())["venues"]
    title, body = message(data, venues)
    print(title, "\n", body)
    if args.dry_run:
        return 0
    key = os.environ.get("ONESIGNAL_API_KEY", "").strip()
    if not key:
        print("No ONESIGNAL_API_KEY; not sending.")
        return 1
    result = send(title, body, key)
    print("OneSignal:", result)
    LOG.write_text(json.dumps({"last": today, "id": result.get("id"), "title": title, "body": body}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
