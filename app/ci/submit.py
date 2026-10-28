#!/usr/bin/env python3
"""Submit the version in "Prepare for Submission" to App Review (App Store Connect API).

  python3 app/ci/submit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc import BUNDLE_ID, call, summary  # noqa: E402

app_id = call("GET", f"/apps?filter[bundleId]={BUNDLE_ID}")["data"][0]["id"]
versions = call("GET", f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS&limit=20")["data"]
version = next((v for v in versions if v["attributes"]["appStoreState"] in
                ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED")), None)
if not version:
    sys.exit("::error::No version waiting to be submitted: " + ", ".join(
        f"{v['attributes']['versionString']} {v['attributes']['appStoreState']}" for v in versions))
vs = version["attributes"]["versionString"]

# reuse an open (not yet submitted) review submission, or start one
subs = call("GET", f"/reviewSubmissions?filter[app]={app_id}&filter[platform]=IOS&limit=20")["data"]
sub = next((s for s in subs if s["attributes"]["state"] == "READY_FOR_REVIEW"), None)
if not sub:
    sub = call("POST", "/reviewSubmissions", {"data": {"type": "reviewSubmissions", "attributes": {"platform": "IOS"},
               "relationships": {"app": {"data": {"type": "apps", "id": app_id}}}}})["data"]
items = call("GET", f"/reviewSubmissions/{sub['id']}/items")["data"]
if not items:
    call("POST", "/reviewSubmissionItems", {"data": {"type": "reviewSubmissionItems", "relationships": {
        "reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}},
        "appStoreVersion": {"data": {"type": "appStoreVersions", "id": version["id"]}}}}})
call("PATCH", f"/reviewSubmissions/{sub['id']}", {"data": {"type": "reviewSubmissions", "id": sub["id"],
     "attributes": {"submitted": True}}})
print(f"::notice::Version {vs} submitted for review")
summary(f"Version {vs} submitted to App Review.\n")
