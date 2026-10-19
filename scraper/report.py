"""Daily coverage report: which venues produced shows, which came back empty or broken."""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date, datetime

from common import NY, ROOT

STATUS_TEXT = {
    "ok": "Shows found",
    "none-tonight": "Page read, nothing tonight",
    "blocked": "Site blocks automated visitors",
    "error": "Page didn't load",
    "robots": "Site asks not to be read automatically",
    "no-location": "Address not found on the map",
    "skipped": "Not read",
}


def write(night: date, rows: list[dict], events: list[dict], ai_usage: dict, path=None) -> dict:
    by_status = Counter(r["status"] for r in rows)
    by_source = Counter(s for e in events for s in (e.get("source") or "").split("+") if s)
    report = {
        "date": night.isoformat(),
        "generated": datetime.now(NY).isoformat(timespec="seconds"),
        "totals": {"venues": len(rows), "shows": len(events), **{k: by_status.get(k, 0) for k in STATUS_TEXT}},
        "shows_by_source": dict(by_source),
        "ai": ai_usage,
        "venues": sorted(rows, key=lambda r: (r["status"] == "ok", r["name"].lower())),
    }
    (path or ROOT / "coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [f"## Lineup for {night.isoformat()}: {len(events)} shows", "",
                 "| Source | Shows |", "|---|---|"] + [f"| {k} | {v} |" for k, v in by_source.most_common()]
        lines += ["", f"Venues: {by_status.get('ok', 0)} with shows, {by_status.get('none-tonight', 0)} nothing tonight, "
                      f"{by_status.get('blocked', 0)} blocked, {by_status.get('error', 0)} errors.", ""]
        if ai_usage.get("calls"):
            lines += [f"AI: {ai_usage['calls']} pages, {ai_usage['input_tokens']:,} input / "
                      f"{ai_usage['output_tokens']:,} output tokens, about ${ai_usage['cost_usd']:.3f}.", ""]
        problems = [r for r in rows if r["status"] in ("blocked", "error", "robots", "no-location")]
        if problems:
            lines += ["### Venues needing attention", "", "| Venue | Problem | Detail |", "|---|---|---|"]
            lines += [f"| {r['name']} | {STATUS_TEXT[r['status']]} | {(r.get('detail') or '').replace('|', '/')[:120]} |"
                      for r in problems]
        with open(summary, "a") as f:
            f.write("\n".join(lines) + "\n")
    return report
