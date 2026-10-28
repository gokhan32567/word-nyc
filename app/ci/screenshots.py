#!/usr/bin/env python3
"""App Store screenshots from the real app in the iOS Simulator (6.9-inch iPhone, 1320 x 2868).

Runs on the macOS runner after the simulator build (see .github/workflows/ios.yml). Each shot relaunches
the app with "-WNPath <page>", which the app loads from word-nyc.com; ?now=... freezes the clock at a
lively hour so shows read "Playing now" (and keeps the visit out of the stats). Every simulator command has a
time limit, and timings are printed as GitHub notices.

  python3 app/ci/screenshots.py build/sim/Build/Products/Debug-iphonesimulator/App.app app/store/screenshots
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scraper"))
from common import minutes  # noqa: E402
from pages import slug  # noqa: E402

BUNDLE = "com.wordnyc.app"


T0 = time.time()


def note(msg: str) -> None:
    print(f"::notice::[{time.time() - T0:5.0f}s] {msg}", flush=True)


def sh(*args: str, check: bool = True, timeout: int = 180) -> str:
    print("$", " ".join(args), flush=True)
    try:
        r = subprocess.run(args, check=check, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except subprocess.TimeoutExpired:
        note(f"timed out after {timeout}s: {' '.join(args[:4])}")
        if check:
            raise
        return ""


def pick_device() -> str:
    devices = json.loads(sh("xcrun", "simctl", "list", "devices", "available", "-j"))["devices"]
    phones = [(rt, d) for rt, ds in devices.items() if "iOS" in rt for d in ds if d["name"].startswith("iPhone")]
    for want in ("iPhone 17 Pro Max", "iPhone 16 Pro Max", "Pro Max", "Plus"):
        for rt, d in sorted(phones, key=lambda p: p[0], reverse=True):
            if want in d["name"]:
                print(f"Simulator: {d['name']} ({rt})")
                return d["udid"]
    raise SystemExit("No large iPhone simulator found")


def shows() -> tuple[str | None, str | None]:
    """A show with a photo for the details shot, and a venue with shows tonight for the venue shot."""
    data = json.loads((ROOT / "events.json").read_text())
    evening = [e for e in data["events"] if 19 * 60 <= minutes(e.get("time")) <= 22 * 60]
    with_img = [e for e in evening if e.get("image") and e.get("description")] or evening
    show = venue = None
    if with_img:
        e = with_img[0]
        show = f"{slug(e['venue'])}-{minutes(e.get('time'))}"
    counts: dict[str, int] = {}
    for e in data["events"]:
        counts[e["venue"]] = counts.get(e["venue"], 0) + 1
    for name in ("Village Vanguard", "Blue Note Jazz Club", "Smalls Jazz Club", "Birdland"):
        if counts.get(name):
            venue = slug(name)
            break
    venue = venue or (slug(max(counts, key=counts.get)) if counts else None)
    return show, venue


def main() -> int:
    app, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    udid = pick_device()
    note("booting")
    sh("xcrun", "simctl", "boot", udid, check=False, timeout=300)
    sh("xcrun", "simctl", "bootstatus", udid, "-b", check=False, timeout=600)
    note("booted")
    sh("xcrun", "simctl", "ui", udid, "appearance", "dark", check=False)
    sh("xcrun", "simctl", "status_bar", udid, "override", "--time", "9:41", "--dataNetwork", "wifi", "--wifiMode", "active",
       "--wifiBars", "3", "--cellularMode", "active", "--cellularBars", "4", "--batteryState", "charged", "--batteryLevel", "100",
       check=False)
    sh("xcrun", "simctl", "install", udid, str(app), timeout=300)
    note("installed")
    sh("xcrun", "simctl", "launch", udid, BUNDLE, check=False, timeout=120)
    time.sleep(20)  # first launch: web view warm-up, map tiles

    show, venue = shows()
    shots = [
        ("1-map", "/?now=9:15pm"),
        ("2-list", "/?now=9:15pm&drawer=full"),
        ("3-show", f"/?now=7:15pm&show={show}" if show else None),
        ("4-jazz", "/?now=10:30pm&genre=Jazz"),
        ("5-venue", f"/venues/{venue}/" if venue else None),
    ]
    for name, path in shots:
        if not path:
            continue
        sh("xcrun", "simctl", "launch", "--terminate-running-process", udid, BUNDLE, "-WNPath", path, check=False, timeout=120)
        time.sleep(16)
        target = out / f"{name}.png"
        sh("xcrun", "simctl", "io", udid, "screenshot", "--type=png", str(target), check=False, timeout=60)
        note(f"{name}: {'saved' if target.exists() else 'missing'}")
    sh("xcrun", "simctl", "shutdown", udid, check=False, timeout=120)
    return 0


if __name__ == "__main__":
    sys.exit(main())
