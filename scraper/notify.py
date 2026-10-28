#!/usr/bin/env python3
"""Send the daily "Tonight's picks" push notification through OneSignal (web push and the iPhone app).

What goes out:
- A few evening shows from events.json, one per venue, big-name rooms first.
- Sponsored lead: if sponsored.json has a placement for today with "push": true (the "Featured in the noon
  push" tier on advertise.html), the notification starts with that show, labeled "Sponsored", and tapping it
  opens the show's details. At most one sponsored item per push; other sponsored shows are left out of the
  picks rather than shown unlabeled. With no push placement today the message is unchanged.
- Favorites: people who follow a venue (OneSignal tag fav_<venue-slug>, set by wn.js) that plays tonight get
  the same message plus "Also tonight at your favorites: ...". Each person still gets exactly one
  notification: venues are taken in order and each variant excludes followers of the venues before it.
  Follower counts come from the stats worker, so only venues somebody follows get a variant.

Records the date and notification ids in push-log.json so it never goes out twice, and reports delivery and
open counts of recent notifications to the stats worker (for the sponsor report).

  ONESIGNAL_API_KEY=... STATS_KEY=... python scraper/notify.py   # send today's (once)
  python scraper/notify.py --dry-run                              # print the messages, send nothing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, NY, ROOT, minutes  # noqa: E402
from pages import slug  # noqa: E402  (same venue slugs as the site and wn.js)

APP_ID = "d9f2eefb-d834-4054-92cc-422321667627"
LOG = ROOT / "push-log.json"
SITE = "https://word-nyc.com"
# Only placements sold as "Featured in the noon push" lead the notification. Set to False to let every
# sponsored listing lead it.
PUSH_NEEDS_TIER = True
MAX_FAV_VARIANTS = 15   # extra sends per day for "your favorites" (OneSignal filters allow up to 200 entries)
BODY_MAX = 230


def short_venue(name: str) -> str:
    for a, b in (("Village Vanguard", "the Vanguard"), ("Smalls Jazz Club", "Smalls"), ("Blue Note Jazz Club", "Blue Note"),
                 ("Smoke Jazz Club", "Smoke"), ("The Metropolitan Opera House", "the Met"),
                 ("Metropolitan Opera House", "the Met"), ("David Geffen Hall", "Geffen Hall")):
        if name == a:
            return b
    return name


def show_key(e: dict) -> str:
    """Same key as showKey() in index.html: venue slug + start in minutes into the night."""
    m = minutes(e.get("time"))
    return f"{slug(e['venue'])}-{'tba' if m >= 99999 else m}"


def nice(t: str) -> str:
    return t.title() if t.isupper() else t


def line(e: dict, width: int = 42) -> str:
    t = (e.get("time") or "").replace(":00", "")
    return f"{nice(e['title'])[:width].strip()} at {short_venue(e['venue'])}" + (f", {t}" if t else "")


# ---------------------------------------------------------------- sponsored lead

def push_placements(today: str) -> list[dict]:
    path = ROOT / "sponsored.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for p in data.get("placements", []):
        if (p.get("from") and p["from"] > today) or (p.get("until") and today > p["until"]):
            continue
        if PUSH_NEEDS_TIER and not p.get("push"):
            continue
        out.append(p)
    return out


def sponsored_lead(events: list[dict], today: str) -> dict | None:
    """The one sponsored show that leads today's push, or None."""
    for p in push_placements(today):
        if isinstance(p.get("event"), dict):
            title = (p["event"].get("title") or "").lower()
            cands = [e for e in events if e.get("sponsored") and e["title"].lower() == title
                     and slug(e["venue"]) == slug(p["event"].get("venue") or "")]
        else:
            words = (p.get("title_contains") or "").lower()
            cands = [e for e in events if e.get("sponsored") and slug(e["venue"]) == slug(p.get("venue") or "")
                     and (not words or words in e["title"].lower())]
        cands = [e for e in cands if minutes(e.get("time")) >= 12 * 60]  # still ahead of us at noon
        if cands:
            return sorted(cands, key=lambda e: minutes(e.get("time")))[0]
    return None


# ---------------------------------------------------------------- picks

def pick(events: list[dict], venues: list[dict], n: int = 3, skip: set[str] | None = None) -> list[dict]:
    star = {v["name"] for v in venues if v.get("nightly")} | {
        "Carnegie Hall", "David Geffen Hall", "Metropolitan Opera House", "David H. Koch Theater", "Roulette",
        "The Stone", "National Sawdust", "Le Poisson Rouge", "Jazz at Lincoln Center", "Dizzy's Club", "BAM",
        "Chamber Music Society of Lincoln Center", "Brooklyn Steel", "Webster Hall", "Bowery Ballroom"}
    # Sponsored shows never appear as plain picks: only the one sponsored lead, labeled, may appear.
    evening = [e for e in events if 17 * 60 <= minutes(e.get("time")) <= 23 * 60 + 30 and not e.get("sponsored")]
    ranked = sorted(evening, key=lambda e: (e["venue"] not in star, abs(minutes(e.get("time")) - 20 * 60), e["venue"]))
    out, seen = [], set(skip or ())
    for e in ranked:  # one show per venue
        if e["venue"] in seen:
            continue
        seen.add(e["venue"])
        out.append(e)
        if len(out) == n:
            break
    return out


def compose(count: int, lead: dict | None, picks: list[dict], fav_line: str = "") -> tuple[str, str]:
    title = f"Tonight in NYC: {count} shows"
    tail = " Tap for the map." if not lead else ""
    for n in range(len(picks), -1, -1):  # drop picks until it fits
        lines = [line(e) for e in picks[:n]]
        if lead:
            body = f"Sponsored: {line(lead, 48)}." + (f" Also tonight: {' · '.join(lines)}." if lines else "")
        else:
            body = " · ".join(lines) + "." if lines else "Tonight's shows are on the map."
        body += (f" {fav_line}" if fav_line else "") + tail
        if len(body) <= BODY_MAX:
            return title, body
    return title, body[:BODY_MAX - 1].rstrip() + "…"


# ---------------------------------------------------------------- favorites

def stats_url() -> str:
    """The stats worker's address, written into wn.js by the deploy workflow."""
    try:
        m = re.search(r"var STATS_URL = '([^']*)'", (ROOT / "wn.js").read_text())
        return m.group(1).rstrip("/") if m else ""
    except OSError:
        return ""


def followers() -> dict[str, int]:
    url, key = stats_url(), os.environ.get("STATS_KEY", "").strip()
    if not url or not key:
        return {}
    try:
        req = urllib.request.Request(f"{url}/followers?key={urllib.parse.quote(key)}", headers={"User-Agent": "word-nyc-notify"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return {k: int(v) for k, v in json.loads(r.read().decode()).get("followers", {}).items() if int(v) > 0}
    except Exception as e:  # noqa: BLE001 - the push must go out even if the stats worker is down
        print(f"Couldn't read follower counts ({e}); sending without favorites.")
        return {}


def fav_variants(events: list[dict], picked: list[dict], fans: dict[str, int]) -> list[dict]:
    """[{slug, venue, event}] for followed venues playing tonight, most-followed first."""
    taken = {slug(e["venue"]) for e in picked}
    first: dict[str, dict] = {}
    for e in sorted(events, key=lambda e: minutes(e.get("time"))):
        s = slug(e["venue"])
        if s in fans and s not in taken and s not in first and 12 * 60 <= minutes(e.get("time")) < 99999:
            first[s] = e
    order = sorted(first, key=lambda s: (-fans[s], s))[:MAX_FAV_VARIANTS]
    return [{"slug": s, "venue": first[s]["venue"], "event": first[s]} for s in order]


# ---------------------------------------------------------------- OneSignal

def api(method: str, path: str, api_key: str, body: dict | None = None) -> dict:
    """New OneSignal keys use 'Key', older REST API keys use 'Basic'; try both."""
    for scheme in ("Key", "Basic"):
        req = urllib.request.Request(
            f"https://api.onesignal.com{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Authorization": f"{scheme} {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            print(f"OneSignal said {e.code} with '{scheme}' auth: {detail}")
            if e.code != 401 or scheme == "Basic":
                raise
    return {}


def payload(title: str, body: str, path: str, audience: dict) -> dict:
    return {
        "app_id": APP_ID, "target_channel": "push", **audience,
        "headings": {"en": title}, "contents": {"en": body},
        "web_url": SITE + path,                 # web push: opens the site
        "data": {"path": path},                 # iPhone app: handled in the app (no browser hop)
        "chrome_web_icon": f"{SITE}/icons/icon-192.png",
        "ttl": 6 * 3600,
    }


def tag(key: str, relation: str) -> dict:
    return {"field": "tag", "key": key, "relation": relation}


# ---------------------------------------------------------------- push stats -> stats worker

def report_stats(log: dict, api_key: str) -> None:
    """Send delivered/opened counts of the last week's notifications to the stats worker."""
    url, key = stats_url(), os.environ.get("STATS_KEY", "").strip()
    if not url or not key:
        return
    since = (datetime.now(NY).date() - timedelta(days=7)).isoformat()
    rows = []
    for h in log.get("history", []):
        if h.get("date", "") < since or not h.get("id"):
            continue
        try:
            n = api("GET", f"/notifications/{h['id']}?app_id={APP_ID}", api_key)
        except Exception as e:  # noqa: BLE001
            print(f"  stats for {h['id']} unavailable: {e}")
            continue
        plat = n.get("platform_delivery_stats") or {}
        rows.append({"id": h["id"], "day": h["date"], "kind": h.get("kind", "base"), "sponsor": h.get("sponsor", ""),
                     "fav": h.get("fav", ""), "sent": int(n.get("successful") or 0), "opened": int(n.get("converted") or 0),
                     "ios": int((plat.get("ios") or {}).get("successful") or 0)})
    if not rows:
        return
    try:
        req = urllib.request.Request(f"{url}/push", method="POST", data=json.dumps({"rows": rows}).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                              "User-Agent": "word-nyc-notify"})
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"Reported {len(rows)} notification(s) to the stats worker: {r.status}")
    except Exception as e:  # noqa: BLE001
        print(f"Couldn't report push stats: {e}")


# ---------------------------------------------------------------- main

def plan(data: dict, venues: list[dict], today: str, fans: dict[str, int]) -> list[dict]:
    """Every notification to send today: [{kind, title, body, path, audience, sponsor, fav}]."""
    events = data["events"]
    lead = sponsored_lead(events, today)
    skip = {lead["venue"]} if lead else set()
    picks = pick(events, venues, skip=skip)
    path = f"/?show={urllib.parse.quote(show_key(lead))}&source=noon" if lead else "/?source=noon"
    sponsor = slug(lead["venue"]) if lead else ""
    variants = fav_variants(events, picks + ([lead] if lead else []), fans)

    sends = []
    for i, v in enumerate(variants):
        fav_line = f"Also tonight at your favorites: {line(v['event'], 34)}."
        title, body = compose(len(events), lead, picks, fav_line)
        filters = [tag(f"fav_{v['slug']}", "exists")] + [tag(f"fav_{w['slug']}", "not_exists") for w in variants[:i]]
        sends.append({"kind": "fav", "fav": v["slug"], "title": title, "body": body, "path": path, "sponsor": sponsor,
                      "audience": {"filters": filters}})
    title, body = compose(len(events), lead, picks)
    audience = ({"filters": [tag(f"fav_{v['slug']}", "not_exists") for v in variants]} if variants
                else {"included_segments": ["Total Subscriptions"]})
    sends.insert(0, {"kind": "base", "fav": "", "title": title, "body": body, "path": path, "sponsor": sponsor,
                     "audience": audience})
    return sends


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="send even if today's already went out")
    ap.add_argument("--fans", help="dry runs: JSON of follower counts, e.g. '{\"smalls-jazz-club\": 3}'")
    args = ap.parse_args()

    today = datetime.now(NY).date().isoformat()
    data = json.loads((ROOT / "events.json").read_text())
    if data.get("date") != today and not args.dry_run:
        print(f"Lineup is for {data.get('date')}, not today ({today}); not sending.")
        return 1
    if args.dry_run and data.get("date"):
        today = data["date"]
    log = json.loads(LOG.read_text()) if LOG.exists() else {}
    if log.get("last") == today and not args.force and not args.dry_run:
        print(f"Already sent today ({today}).")
        return 0
    venues = json.loads((HERE / "venues.json").read_text())["venues"]
    key = os.environ.get("ONESIGNAL_API_KEY", "").strip()

    fans = json.loads(args.fans) if args.fans else followers()
    sends = plan(data, venues, today, fans)
    for s in sends:
        who = "everyone else" if s["kind"] == "base" and len(sends) > 1 else ("everyone" if s["kind"] == "base" else f"followers of {s['fav']}")
        print(f"[{who}] {s['title']}\n  {s['body']}\n  opens {s['path']}")
    if args.dry_run:
        return 0
    if not key:
        print("No ONESIGNAL_API_KEY; not sending.")
        return 1


    if not log.get("history") and log.get("id") and log.get("last"):  # push-log.json from before history was kept
        log["history"] = [{"date": log["last"], "id": log["id"], "kind": "base", "sponsor": "", "fav": ""}]
    history = [h for h in log.get("history", []) if h.get("date", "") >= (date.fromisoformat(today) - timedelta(days=120)).isoformat()]
    report_stats({"history": history}, key)  # yesterday's numbers have settled by now
    sent_ids = []
    for s in sends:
        try:
            result = api("POST", "/notifications", key, payload(s["title"], s["body"], s["path"], s["audience"]))
        except urllib.error.HTTPError:
            if s["kind"] == "base":
                raise
            continue  # a favorites variant failing shouldn't stop the rest
        print("OneSignal:", result)
        nid = result.get("id") or ""
        if nid:
            sent_ids.append(nid)
            history.append({"date": today, "id": nid, "kind": s["kind"], "sponsor": s["sponsor"], "fav": s["fav"]})
    base = sends[0]
    LOG.write_text(json.dumps({"last": today, "id": sent_ids[0] if sent_ids else None, "title": base["title"],
                               "body": base["body"], "history": history}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
