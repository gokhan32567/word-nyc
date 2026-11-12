#!/usr/bin/env python3
"""Read-only: where the app is in App Store review (versions, review submissions, builds)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc import BUNDLE_ID, call, summary  # noqa: E402

app = call("GET", f"/apps?filter[bundleId]={BUNDLE_ID}")["data"][0]
app_id = app["id"]
lines = [f"App: {app['attributes'].get('name')} ({BUNDLE_ID}), Apple ID {app_id}"]
for v in call("GET", f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS&limit=10")["data"]:
    a = v["attributes"]
    lines.append(f"Version {a['versionString']}: {a['appStoreState']} (created {a.get('createdDate')})")
for s in call("GET", f"/reviewSubmissions?filter[app]={app_id}&filter[platform]=IOS&limit=10")["data"]:
    a = s["attributes"]
    lines.append(f"Review submission {s['id'][:8]}: {a.get('state')} submitted {a.get('submittedDate')}")
for b in call("GET", f"/builds?filter[app]={app_id}&sort=-uploadedDate&limit=3")["data"]:
    a = b["attributes"]
    lines.append(f"Build {a.get('version')}: {a.get('processingState')} uploaded {a.get('uploadedDate')}")
b = call("GET", f"/bundleIds?filter[identifier]={BUNDLE_ID}")["data"]
if b:
    lines.append(f"Team (App ID prefix): {b[0]['attributes'].get('seedId')}")
print("\n".join(lines))
summary("\n".join(lines) + "\n")
