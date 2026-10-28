#!/usr/bin/env python3
"""TestFlight: an internal tester group "Team" that gets every build, with the App Store Connect users added.
Apple emails each tester an invite to install with the TestFlight app.

  python3 app/ci/beta.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc import BUNDLE_ID, call, summary  # noqa: E402

app_id = call("GET", f"/apps?filter[bundleId]={BUNDLE_ID}")["data"][0]["id"]
groups = call("GET", f"/apps/{app_id}/betaGroups")["data"]
group = next((g for g in groups if g["attributes"].get("isInternalGroup")), None)
if not group:
    group = call("POST", "/betaGroups", {"data": {"type": "betaGroups", "attributes": {
        "name": "Team", "isInternalGroup": True, "hasAccessToAllBuilds": True},
        "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}})["data"]
    print("Created internal group Team")
gid = group["id"]
print(f"Internal group: {group['attributes']['name']} ({gid})")

users = call("GET", "/users?limit=50")["data"]
existing = {t["attributes"].get("email", "").lower() for t in call("GET", f"/betaGroups/{gid}/betaTesters?limit=200")["data"]}
added = []
for u in users:
    email = u["attributes"]["username"]
    if email.lower() in existing:
        continue
    call("POST", "/betaTesters", {"data": {"type": "betaTesters", "attributes": {
        "email": email, "firstName": u["attributes"].get("firstName", ""), "lastName": u["attributes"].get("lastName", "")},
        "relationships": {"betaGroups": {"data": [{"type": "betaGroups", "id": gid}]}}}}, ok=(201, 409))
    added.append(email)
print(f"::notice::TestFlight group ready; testers added: {len(added)} (already in: {len(existing)})")
summary(f"TestFlight internal group ready. Testers added: {len(added)}. Check your email for the invite.\n")
