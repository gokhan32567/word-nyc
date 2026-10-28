#!/usr/bin/env python3
"""App Store Connect helpers for the TestFlight workflow (.github/workflows/ios.yml).

Uses the App Store Connect API key from the environment: ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_P8 (the .p8 text).

  python3 app/ci/asc.py setup        # register the bundle ID with Push Notifications; check the app record exists
  python3 app/ci/asc.py cert-key     # print the path of the distribution certificate's private key (see below)
  python3 app/ci/asc.py sign PROFILE # point the Xcode project at a provisioning profile, write ExportOptions.plist

The distribution certificate's private key is created once and kept in the repo encrypted
(app/ci/dist-cert-key.enc, AES-256-GCM with a key derived from ASC_KEY_P8), so every build reuses the same
certificate instead of creating a new one (Apple allows only a few). Without ASC_KEY_P8 the file is useless.
If you rotate the API key, a new certificate key is created on the next build.
"""
from __future__ import annotations

import base64
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path

import jwt  # PyJWT
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

BUNDLE_ID = "com.wordnyc.app"
APP_NAME = "Word NYC"
HERE = Path(__file__).resolve().parent
APP = HERE.parent
PBXPROJ = APP / "ios" / "App" / "App.xcodeproj" / "project.pbxproj"
KEY_FILE = HERE / "dist-cert-key.enc"
API = "https://api.appstoreconnect.apple.com/v1"


def env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        sys.exit(f"::error::Missing secret {name}. Add it in GitHub: Settings > Secrets and variables > Actions.")
    return v


def p8() -> str:
    raw = env("ASC_KEY_P8").replace("\\n", "\n")
    if "BEGIN PRIVATE KEY" not in raw:  # pasted without the header lines, or base64 of the file
        try:
            raw = base64.b64decode(raw).decode()
        except Exception:  # noqa: BLE001
            raw = "-----BEGIN PRIVATE KEY-----\n" + raw + "\n-----END PRIVATE KEY-----\n"
    return raw.strip() + "\n"


def token() -> str:
    now = int(time.time())
    return jwt.encode({"iss": env("ASC_ISSUER_ID"), "iat": now, "exp": now + 1100, "aud": "appstoreconnect-v1"},
                      p8(), algorithm="ES256", headers={"kid": env("ASC_KEY_ID"), "typ": "JWT"})


def call(method: str, path: str, body: dict | None = None, ok=(200, 201, 204)) -> dict:
    r = requests.request(method, API + path, json=body, timeout=60,
                         headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:600]}")
    return r.json() if r.content else {}


# ---------------------------------------------------------------- setup

def setup() -> None:
    found = [b for b in call("GET", f"/bundleIds?filter[identifier]={BUNDLE_ID}&limit=200")["data"]
             if b["attributes"]["identifier"] == BUNDLE_ID]
    if found:
        bid = found[0]["id"]
        print(f"Bundle ID {BUNDLE_ID} is registered ({bid}).")
    else:
        bid = call("POST", "/bundleIds", {"data": {"type": "bundleIds", "attributes": {
            "identifier": BUNDLE_ID, "name": APP_NAME, "platform": "IOS"}}})["data"]["id"]
        print(f"Registered bundle ID {BUNDLE_ID} ({bid}).")
    caps = {c["attributes"]["capabilityType"] for c in call("GET", f"/bundleIds/{bid}/bundleIdCapabilities")["data"]}
    if "PUSH_NOTIFICATIONS" not in caps:
        call("POST", "/bundleIdCapabilities", {"data": {"type": "bundleIdCapabilities",
             "attributes": {"capabilityType": "PUSH_NOTIFICATIONS"},
             "relationships": {"bundleId": {"data": {"type": "bundleIds", "id": bid}}}}}, ok=(201, 409))
        print("Turned on Push Notifications for the bundle ID.")
    apps = call("GET", f"/apps?filter[bundleId]={BUNDLE_ID}")["data"]
    if not apps:
        msg = (f"The bundle ID is ready, but there's no app record yet. In App Store Connect > Apps > + > New App, "
               f"choose iOS, name '{APP_NAME}', bundle ID {BUNDLE_ID}, SKU word-nyc-ios, then run this workflow again.")
        print(f"::error::{msg}")
        summary(f"### Next step\n{msg}\n")
        sys.exit(1)
    print(f"App record: {apps[0]['attributes']['name']} (Apple ID {apps[0]['id']}).")
    summary(f"App Store Connect app: {apps[0]['attributes']['name']}, Apple ID {apps[0]['id']}\n")


def summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write(text + "\n")


# ---------------------------------------------------------------- certificate key

def _aes() -> AESGCM:
    kdf = Scrypt(salt=b"word-nyc-dist-cert-key-v1", length=32, n=2 ** 15, r=8, p=1)
    return AESGCM(kdf.derive(p8().encode()))


def cert_key() -> None:
    out = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "dist-cert-key.pem"
    if KEY_FILE.exists():
        blob = KEY_FILE.read_bytes()
        try:
            pem = _aes().decrypt(blob[:12], blob[12:], None)
            out.write_bytes(pem)
            print(out)
            return
        except Exception:  # noqa: BLE001
            print("::warning::Couldn't decrypt app/ci/dist-cert-key.enc (new API key?); creating a new certificate key.",
                  file=sys.stderr)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                            serialization.NoEncryption())
    nonce = os.urandom(12)
    KEY_FILE.write_bytes(nonce + _aes().encrypt(nonce, pem, None))
    out.write_bytes(pem)
    print(out)


# ---------------------------------------------------------------- project signing

def sign(profile_path: str) -> None:
    raw = subprocess.run(["security", "cms", "-D", "-i", profile_path], check=True, capture_output=True).stdout
    prof = plistlib.loads(raw)
    team, name, uuid = prof["TeamIdentifier"][0], prof["Name"], prof["UUID"]
    print(f"Profile '{name}' ({uuid}), team {team}")
    if "aps-environment" not in prof.get("Entitlements", {}):
        print("::warning::The profile has no Push Notifications entitlement; notifications won't work in this build.")

    text = PBXPROJ.read_text()
    # Only the App target's Release configuration (it has INFOPLIST_FILE); Swift packages keep their own settings.
    def patch(m: re.Match) -> str:
        block = m.group(0)
        if "INFOPLIST_FILE = App/Info.plist;" not in block:
            return block
        block = re.sub(r"\t+CODE_SIGN_STYLE = [^;]+;\n", "", block)
        block = re.sub(r"\t+(DEVELOPMENT_TEAM|PROVISIONING_PROFILE_SPECIFIER|\"CODE_SIGN_IDENTITY\[sdk=iphoneos\*\]\"|CODE_SIGN_IDENTITY) = [^;]+;\n", "", block)
        settings = (f'\t\t\t\tCODE_SIGN_IDENTITY = "Apple Distribution";\n\t\t\t\tCODE_SIGN_STYLE = Manual;\n'
                    f'\t\t\t\tDEVELOPMENT_TEAM = {team};\n\t\t\t\tPROVISIONING_PROFILE_SPECIFIER = "{name}";\n')
        return block.replace("buildSettings = {\n", "buildSettings = {\n" + settings, 1)
    new = re.sub(r"[0-9A-F]{24} /\* Release \*/ = \{\n\t+isa = XCBuildConfiguration;.*?name = Release;\n\t+\};", patch, text, flags=re.S)
    if new.count("PROVISIONING_PROFILE_SPECIFIER") != 1:
        sys.exit("::error::Couldn't find the App target's Release configuration in project.pbxproj")
    PBXPROJ.write_text(new)

    export = {
        "method": "app-store-connect",
        "teamID": team,
        "signingStyle": "manual",
        "provisioningProfiles": {BUNDLE_ID: name},
        "signingCertificate": "Apple Distribution",
        "uploadSymbols": True,
        "manageAppVersionAndBuildNumber": False,
        "destination": os.environ.get("EXPORT_DESTINATION", "upload"),
    }
    Path(os.environ.get("RUNNER_TEMP", "/tmp"), "ExportOptions.plist").write_bytes(plistlib.dumps(export))
    print(json.dumps(export, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "cert-key":
        cert_key()
    elif cmd == "sign" and len(sys.argv) > 2:
        sign(sys.argv[2])
    else:
        sys.exit(__doc__)
