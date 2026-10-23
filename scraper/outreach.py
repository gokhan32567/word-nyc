#!/usr/bin/env python3
"""Send the founding-venue email, one message per venue, from the Word NYC Gmail.

  LISTINGS_EMAIL=... LISTINGS_APP_PASSWORD=... python scraper/outreach.py outreach/founding-venues.csv --test
  ... python scraper/outreach.py outreach/founding-venues.csv --send

Already-sent venues are recorded in outreach/sent.json and never emailed twice.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

REPLY_TO = "advertise@word-nyc.com"
SUBJECT = "{venue} is on Word NYC, tonight's NYC show map"
BODY = """Hi {venue} team,

We run Word NYC (word-nyc.com), a free live map of tonight's music shows across New York. People open it when they're deciding where to go in the next few hours, and {venue} is already on it: your shows are pulled from your calendar every morning.

We're offering founding venues a featured spot: your show at the top of the map and list, a highlighted pin, and first place in the graphic people share to Instagram. The first week is free. After that it's $10 a night, $39 a week or $99 a month, with no contract, and founding rates are locked in for six months.

If you'd like the free week, just reply with the night(s) you want featured. And if any of your listings look wrong or a show is missing, tell us and we'll fix it.

Thanks,
The creators of Word NYC
word-nyc.com

Word NYC, 307 W 38th St, 16th Floor PMB 257, New York, NY 10018
Not interested? Reply "no thanks" and we won't email again.
"""


def message(sender: str, to: str, venue: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = formataddr(("Word NYC", sender))
    m["To"] = to
    m["Reply-To"] = REPLY_TO
    m["Subject"] = SUBJECT.format(venue=venue)
    m["List-Unsubscribe"] = f"<mailto:{REPLY_TO}?subject=unsubscribe>"
    m.set_content(BODY.format(venue=venue))
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--send", action="store_true", help="email every venue not yet sent")
    ap.add_argument("--test", action="store_true", help="send one sample to the Word NYC inbox only")
    ap.add_argument("--gap", type=int, default=60, help="seconds between emails")
    args = ap.parse_args()
    sender = os.environ["LISTINGS_EMAIL"].strip()
    password = re.sub(r"\s+", "", os.environ["LISTINGS_APP_PASSWORD"])
    rows = list(csv.DictReader(open(args.csv)))
    log_path = Path(args.csv).parent / "sent.json"
    sent = json.loads(log_path.read_text()) if log_path.exists() else {}
    todo = [r for r in rows if r["email"].lower() not in sent]
    if args.test:
        todo = [{"venue": rows[0]["venue"], "email": sender}]
    elif not args.send:
        for r in todo:
            print("would send:", r["venue"], r["email"])
        return 0
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(sender, password)
        for i, r in enumerate(todo):
            if i:
                time.sleep(args.gap)
            s.send_message(message(sender, r["email"], r["venue"]))
            print(f"sent {r['venue']} <{r['email']}>", flush=True)
            if not args.test:
                sent[r["email"].lower()] = {"venue": r["venue"], "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                log_path.write_text(json.dumps(sent, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
