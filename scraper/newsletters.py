"""Shows from venue newsletters, for venues whose websites can't be read.

Venues email their upcoming shows to the Word NYC listings inbox (LISTINGS_EMAIL). Each run reads the
last few weeks of mail over IMAP (LISTINGS_APP_PASSWORD is a Gmail app password), works out which
venue sent each email, and has the AI reader pull out tonight's shows with the same checks as venue
pages: the date, time and title must all appear in the email.

  LISTINGS_EMAIL=... LISTINGS_APP_PASSWORD=... python scraper/newsletters.py --dry-run
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import re
import urllib.parse
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from common import NY, log
from shows import place_key

DAYS_BACK = 28
MAX_EMAILS = 400


class _Text(HTMLParser):
    """HTML email -> readable text plus its links."""
    SKIP = {"style", "script", "head", "title"}
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "td"}

    def __init__(self):
        super().__init__()
        self.out, self.links, self._skip, self._href, self._atext = [], [], 0, None, []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a":
            self._href, self._atext = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and self._href:
            text = " ".join("".join(self._atext).split())[:90]
            if self._href.startswith("http"):
                self.links.append({"text": text, "href": self._href})
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)
            if self._href:
                self._atext.append(data)

    def text(self) -> str:
        t = "".join(self.out).replace("\xa0", " ")
        t = re.sub(r"[ \t]+", " ", t)
        return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _body(msg) -> tuple[str, list[dict]]:
    html = plain = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        try:
            content = part.get_content()
        except Exception:  # noqa: BLE001 - odd encodings: skip that part
            continue
        if ctype == "text/html" and html is None:
            html = content
        elif ctype == "text/plain" and plain is None:
            plain = content
    if html:
        p = _Text()
        p.feed(html)
        return p.text(), p.links
    links = [{"text": "", "href": u} for u in re.findall(r"https?://[^\s<>\"')\]]+", plain or "")]
    return (plain or "").strip(), links


def _domain(url_or_addr: str) -> str:
    host = url_or_addr.split("@")[-1] if "@" in url_or_addr and "//" not in url_or_addr \
        else urllib.parse.urlsplit(url_or_addr).netloc
    parts = host.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.lower()


GENERIC_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "mailchimp.com", "mcsv.net",
                   "mailchimpapp.net", "squarespace.com", "constantcontact.com", "eventbrite.com", "dice.fm",
                   "seetickets.us", "wix.com", "aol.com", "icloud.com", "substack.com", "google.com"}


def which_venue(sender_name: str, sender_addr: str, venues: list[dict]) -> dict | None:
    """The venue an email comes from: an explicit 'newsletter' sender, the website's domain, or the name."""
    addr = sender_addr.lower()
    for v in venues:
        for s in v.get("newsletter") or []:
            if s.lower() in addr:
                return v
    dom = _domain(addr)
    if dom not in GENERIC_DOMAINS:
        for v in venues:
            if _domain(v["url"]) == dom:
                return v
    who = place_key(sender_name)
    if who:
        for v in sorted(venues, key=lambda v: -len(place_key(v["name"]))):
            k = place_key(v["name"])
            if k and len(k) >= 4 and (k == who or re.search(rf"\b{re.escape(k)}\b", who)
                                      or (len(who) >= 5 and re.match(rf"{re.escape(who)}\b", k))):
                return v
    return None


def fetch(user: str, password: str, days: int = DAYS_BACK) -> list[dict]:
    since = (datetime.now(NY) - timedelta(days=days)).strftime("%d-%b-%Y")
    box = imaplib.IMAP4_SSL("imap.gmail.com", timeout=60)
    try:
        box.login(user.strip(), re.sub(r"\s+", "", password))  # app passwords are shown with spaces
        mails = []
        for folder in ('"[Gmail]/All Mail"', "INBOX"):
            typ, _ = box.select(folder, readonly=True)
            if typ == "OK":
                break
        typ, data = box.search(None, "SINCE", since)
        ids = (data[0] or b"").split()[-MAX_EMAILS:]
        for i in reversed(ids):
            typ, parts = box.fetch(i, "(BODY.PEEK[])")
            if typ != "OK" or not parts or not isinstance(parts[0], tuple):
                continue
            msg = email.message_from_bytes(parts[0][1], policy=email.policy.default)
            name, addr = parseaddr(str(msg.get("From", "")))
            try:
                sent = parsedate_to_datetime(str(msg.get("Date"))).astimezone(NY)
            except Exception:  # noqa: BLE001
                sent = None
            text, links = _body(msg)
            mails.append({"from_name": name, "from": addr, "subject": str(msg.get("Subject", "")),
                          "sent": sent, "text": text, "links": links})
        return mails
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass


def confirm_links(mails: list[dict], venues: list[dict]) -> list[tuple[str, str]]:
    """Subscription-confirmation links in emails from our venues (opened by hand, never automatically)."""
    out = []
    for m in mails:
        if re.search(r"confirm|verify|activate", m["subject"], re.I) and which_venue(m["from_name"], m["from"], venues):
            for ln in m["links"]:
                if re.search(r"confirm|verify|subscribe|activate|yes", ln["text"] + " " + ln["href"], re.I):
                    out.append((m["from"], ln["href"]))
                    break
    return out


def newsletter_events(venues: list[dict], night: date, ai_key: str, user: str, password: str) -> tuple[list[dict], list[dict]]:
    """Returns (events, coverage rows) for tonight from the listings inbox."""
    import ai
    from browse import Snapshot, tonight_pattern
    from shows import is_show, is_strict

    mails = fetch(user, password)
    log(f"  newsletters: {len(mails)} emails in the last {DAYS_BACK} days")
    recent = [m for m in mails if m["sent"] and (datetime.now(NY) - m["sent"]).days <= 3]
    for who, link in confirm_links(recent, venues):  # finish double opt-in signups from our venues
        try:
            import urllib.request
            urllib.request.urlopen(urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read(2000)
            log(f"  newsletters: confirmed subscription from {who}")
        except Exception as e:  # noqa: BLE001
            log(f"  newsletters: couldn't confirm {who}: {type(e).__name__}")
    pat = tonight_pattern(night)
    events, rows, calls = [], [], 0
    for m in mails:
        v = which_venue(m["from_name"], m["from"], venues)
        if not v or not m["text"] or not pat.search(m["text"]):
            continue
        if m["sent"] and m["sent"].date() > night:
            continue
        sent = m["sent"].strftime("%A, %B %-d, %Y") if m["sent"] else "an unknown date"
        snap = Snapshot(venue=v["name"], url=v["url"], final_url=v["url"], status=200,
                        text=f"Subject: {m['subject']}\n\n{m['text']}"[:60_000], links=m["links"][:300])
        loaded = (f"This is a newsletter email from the venue, sent on {sent}. 'Today' or 'Tonight' in it means "
                  f"the day it was sent, so only use them if that is the night to report.")
        try:
            found, info = ai.extract(snap, v, night, ai_key, loaded=loaded)
        except ai.AIError as e:
            log(f"  newsletter from {v['name']}: {e}")
            continue
        calls += 1
        found = [e for e in found if v.get("all_events") or is_show(e["title"], "", is_strict(v))]
        for e in found:
            e.pop("_presenter", None)
            e["source"] = "newsletter"
        events += found
        rows.append({"name": v["name"], "url": v["url"], "read_url": f"email: {m['subject'][:80]}",
                     "method": "newsletter", "status": "ok" if found else "none-tonight", "shows": len(found),
                     "detail": f"sent {sent}", "tokens": [info["input_tokens"], info["output_tokens"]],
                     "examples": info.get("examples")})
        if calls >= 40:
            break
    return events, rows


if __name__ == "__main__":
    import argparse
    import json
    import os
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import HERE, current_night
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list emails and their venues, no AI")
    args = ap.parse_args()
    venues = json.loads((HERE / "venues.json").read_text())["venues"]
    mails = fetch(os.environ["LISTINGS_EMAIL"], os.environ["LISTINGS_APP_PASSWORD"])
    for m in mails:
        v = which_venue(m["from_name"], m["from"], venues)
        print(f"{m['sent']:%m-%d} {m['from'][:40]:40} -> {v['name'] if v else '?'} | {m['subject'][:60]}")
    for who, link in confirm_links(mails, venues):
        print("CONFIRM", who, link)
