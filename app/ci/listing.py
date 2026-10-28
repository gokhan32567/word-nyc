#!/usr/bin/env python3
"""Fill the App Store listing from app/store/listing.json and app/store/screenshots, through the App Store
Connect API (same key as the build). Safe to run again: it overwrites the text and replaces the screenshots.

Does: name, subtitle, privacy policy URL, categories, content rights, version number, copyright,
description, keywords, promotional text, support/marketing URLs, 6.9" screenshots, and picks the newest
processed build. Not in Apple's API, so done by hand: App Privacy answers, age rating, App Review contact.

  python3 app/ci/listing.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asc import BUNDLE_ID, call, summary  # noqa: E402

STORE = Path(__file__).resolve().parents[1] / "store"
L = json.loads((STORE / "listing.json").read_text())
problems: list[str] = []


def step(name):
    def wrap(fn):
        def run(*a):
            try:
                result = fn(*a)
                print(f"::notice::{name}: done")
                return result
            except Exception as e:  # noqa: BLE001 - report and carry on with the rest
                problems.append(f"{name}: {e}")
                print(f"::error::{name}: {str(e)[:900]}")
        return run
    return wrap


def first(data, **match):
    for d in data:
        if all(d["attributes"].get(k) == v for k, v in match.items()):
            return d
    return None


@step("App information (name, subtitle, privacy URL, categories)")
def app_info(app_id):
    infos = call("GET", f"/apps/{app_id}/appInfos")["data"]
    info = next((i for i in infos if i["attributes"].get("appStoreState") not in ("READY_FOR_SALE", "REPLACED_WITH_NEW_INFO")), infos[0])
    locs = call("GET", f"/appInfos/{info['id']}/appInfoLocalizations")["data"]
    loc = first(locs, locale="en-US") or locs[0]
    call("PATCH", f"/appInfoLocalizations/{loc['id']}", {"data": {"type": "appInfoLocalizations", "id": loc["id"], "attributes": {
        "name": L["name"], "subtitle": L["subtitle"], "privacyPolicyUrl": L["privacyPolicyUrl"]}}})
    call("PATCH", f"/appInfos/{info['id']}", {"data": {"type": "appInfos", "id": info["id"], "relationships": {
        "primaryCategory": {"data": {"type": "appCategories", "id": L["primaryCategory"]}},
        "secondaryCategory": {"data": {"type": "appCategories", "id": L["secondaryCategory"]}}}}})


@step("Content rights")
def content_rights(app_id):
    call("PATCH", f"/apps/{app_id}", {"data": {"type": "apps", "id": app_id, "attributes": {
        "contentRightsDeclaration": L["contentRights"]}}})


def editable_version(app_id):
    vs = call("GET", f"/apps/{app_id}/appStoreVersions?filter[platform]=IOS&limit=20")["data"]
    for v in vs:
        if v["attributes"]["appStoreState"] in ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED"):
            return v
    raise RuntimeError("no version in 'Prepare for Submission'")


@step("Version number and copyright")
def version_info(version):
    call("PATCH", f"/appStoreVersions/{version['id']}", {"data": {"type": "appStoreVersions", "id": version["id"], "attributes": {
        "versionString": L["version"], "copyright": L["copyright"]}}})


@step("Description, keywords, promotional text, URLs")
def version_text(loc):
    call("PATCH", f"/appStoreVersionLocalizations/{loc['id']}", {"data": {"type": "appStoreVersionLocalizations", "id": loc["id"],
         "attributes": {"description": L["description"], "keywords": L["keywords"], "promotionalText": L["promotionalText"],
                        "supportUrl": L["supportUrl"], "marketingUrl": L["marketingUrl"]}}})


def upload_screenshot(set_id: str, path: Path):
    data = path.read_bytes()
    shot = call("POST", "/appScreenshots", {"data": {"type": "appScreenshots",
                "attributes": {"fileName": path.name, "fileSize": len(data)},
                "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": set_id}}}}})["data"]
    for op in shot["attributes"]["uploadOperations"]:
        chunk = data[op["offset"]:op["offset"] + op["length"]]
        headers = {h["name"]: h["value"] for h in op.get("requestHeaders") or []}
        r = requests.request(op["method"], op["url"], data=chunk, headers=headers, timeout=120)
        r.raise_for_status()
    call("PATCH", f"/appScreenshots/{shot['id']}", {"data": {"type": "appScreenshots", "id": shot["id"], "attributes": {
        "uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})


@step("Screenshots (6.9-inch iPhone)")
def screenshots(loc):
    sets = call("GET", f"/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets")["data"]
    errors = []
    for display in ("APP_IPHONE_67", "APP_IPHONE_69"):  # Apple files 6.9" screenshots under one of these
        s = first(sets, screenshotDisplayType=display)
        try:
            if not s:
                s = call("POST", "/appScreenshotSets", {"data": {"type": "appScreenshotSets",
                         "attributes": {"screenshotDisplayType": display},
                         "relationships": {"appStoreVersionLocalization": {"data": {"type": "appStoreVersionLocalizations", "id": loc["id"]}}}}})["data"]
            for old in call("GET", f"/appScreenshotSets/{s['id']}/appScreenshots")["data"]:
                call("DELETE", f"/appScreenshots/{old['id']}")
            for name in L["screenshots"]:
                upload_screenshot(s["id"], STORE / "screenshots" / name)
            print(f"Uploaded {len(L['screenshots'])} screenshots as {display}")
            return
        except Exception as e:  # noqa: BLE001
            errors.append(f"{display}: {e}")
    raise RuntimeError(" | ".join(errors))


@step("Build for this version")
def pick_build(app_id, version):
    builds = call("GET", f"/builds?filter[app]={app_id}&filter[processingState]=VALID&sort=-uploadedDate&limit=1")["data"]
    if not builds:
        raise RuntimeError("no processed build yet (Apple is still processing the upload); run this again later")
    b = builds[0]
    call("PATCH", f"/appStoreVersions/{version['id']}/relationships/build", {"data": {"type": "builds", "id": b["id"]}})
    print(f"Build {b['attributes']['version']} selected")


def main() -> int:
    apps = call("GET", f"/apps?filter[bundleId]={BUNDLE_ID}")["data"]
    if not apps:
        sys.exit("::error::No app record for " + BUNDLE_ID)
    app_id = apps[0]["id"]
    app_info(app_id)
    content_rights(app_id)
    version = editable_version(app_id)
    version_info(version)
    locs = call("GET", f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations")["data"]
    loc = first(locs, locale="en-US") or locs[0]
    version_text(loc)
    screenshots(loc)
    pick_build(app_id, version)
    summary("### App Store listing\n" + ("All filled in." if not problems else "Needs attention:\n- " + "\n- ".join(problems)) +
            "\n\nStill by hand: App Privacy, Age Rating, App Review contact details.\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
