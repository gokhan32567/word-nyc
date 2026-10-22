#!/usr/bin/env python3
"""Weekly coverage audit: which venues may be missing shows.

Looks at the last 7 published lineups (git history of events.json / coverage.json) and reports:
  1. venues on our list that produced no shows all week (or were blocked / errored);
  2. venues that appeared through Ticketmaster or submissions but aren't on our list;
  3. nightly venues that came back empty on any day.
Writes audit.md (and audit.json) at the repo root.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, ROOT  # noqa: E402


def history(path: str, days: int = 7) -> list[dict]:
    shas = subprocess.run(["git", "log", "--format=%h", "-n", "60", "--", path], cwd=ROOT,
                          capture_output=True, text=True).stdout.split()
    by_date: dict[str, dict] = {}
    for sha in shas:  # newest first: keep the latest version of each day
        try:
            data = json.loads(subprocess.run(["git", "show", f"{sha}:{path}"], cwd=ROOT,
                                             capture_output=True, text=True).stdout)
        except ValueError:
            continue
        by_date.setdefault(data.get("date"), data)
        if len(by_date) >= days:
            break
    return [by_date[d] for d in sorted(by_date)]


def main() -> int:
    venues = json.loads((HERE / "venues.json").read_text())["venues"]
    listed = {v["name"] for v in venues}
    lineups, coverage = history("events.json"), history("coverage.json")
    days = [d["date"] for d in lineups]

    shows = Counter()
    for d in lineups:
        for e in d["events"]:
            shows[e["venue"]] += 1
    status = defaultdict(Counter)
    for c in coverage:
        for r in c.get("venues", []):
            status[r["name"]][r["status"]] += 1

    silent = sorted(v["name"] for v in venues if not shows[v["name"]] and not v.get("via"))
    broken = sorted(n for n, st in status.items() if st["blocked"] + st["error"] + st["robots"] >= 3)
    outside = sorted(((n, c) for n, c in shows.items() if n not in listed), key=lambda x: -x[1])
    nightly_gaps = {}
    for c in coverage:
        for n in c.get("ai", {}).get("nightly_missing", []) or []:
            nightly_gaps.setdefault(n, []).append(c["date"])

    report = {"days": days, "silent": silent, "broken": broken, "outside": outside[:30], "nightly_gaps": nightly_gaps}
    (ROOT / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    md = [f"# Coverage audit, {days[0]} to {days[-1]}" if days else "# Coverage audit", ""]
    md += [f"Total shows: {sum(shows.values())} over {len(days)} days, at {len(shows)} venues.", ""]
    md += ["## Nightly venues with empty days"] + ([f"- {n}: {', '.join(d)}" for n, d in nightly_gaps.items()] or ["- none"]) + [""]
    md += ["## Our venues with no shows all week"] + ([f"- {n}" for n in silent] or ["- none"]) + [""]
    md += ["## Venues that block us or failed most days"] + ([f"- {n}" for n in broken] or ["- none"]) + [""]
    md += ["## Venues with shows (Ticketmaster/submissions) not on our list"] + ([f"- {n} ({c} shows)" for n, c in outside[:30]] or ["- none"])
    (ROOT / "audit.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
