#!/usr/bin/env python3
"""Find public contact emails for venues (for the venue outreach list).

Opens each venue's home page plus its contact/about/booking pages and collects email addresses
shown there. Writes contacts.json: {venue: {"emails": [...], "pages": [...], "instagram": ...}}.

  python scraper/contacts.py "Ornithology,Terra Blues,..."
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK = re.compile(r"\.(png|jpe?g|gif|webp|svg)$|sentry|wixpress|example\.|@2x|domain\.com|godaddy|squarespace|"
                  r"wordpress|yourname|email@|name@|user@", re.I)
SUBPAGE = re.compile(r"contact|about|booking|book|info|visit|press|private|rental|faq", re.I)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")


async def grab(page, url: str) -> tuple[set[str], list[dict]]:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:  # noqa: BLE001
        pass
    data = await page.evaluate("""() => ({
        html: document.documentElement.innerHTML,
        links: [...document.querySelectorAll('a[href]')].map(a => ({t: (a.innerText||'').trim().slice(0,40), h: a.href}))
    })""")
    emails = {m.lower().strip(".") for m in EMAIL.findall(urllib.parse.unquote(data["html"]))}
    return {e for e in emails if not JUNK.search(e)}, data["links"]


async def one(browser, v: dict, sem) -> tuple[str, dict]:
    async with sem:
        out = {"emails": [], "pages": [], "instagram": None, "error": None}
        ctx = await browser.new_context(user_agent=UA)
        page = await ctx.new_page()
        try:
            home = re.sub(r"(https?://[^/]+).*", r"\1/", v["url"])
            found, links = await grab(page, home)
            out["pages"].append(home)
            host = urllib.parse.urlsplit(home).netloc.replace("www.", "")
            subs = []
            for ln in links:
                h = ln["h"].split("#")[0]
                if "instagram.com/" in h and not out["instagram"]:
                    out["instagram"] = h
                if host in h and SUBPAGE.search(ln["t"] + " " + h) and h not in subs and h.rstrip("/") != home.rstrip("/"):
                    subs.append(h)
            for h in subs[:4]:
                try:
                    more, _ = await grab(page, h)
                    found |= more
                    out["pages"].append(h)
                except Exception:  # noqa: BLE001
                    pass
            rank = lambda e: (host.split(".")[0] not in e, not re.match(r"(info|hello|events?|booking|book|marketing|press|contact)@", e))
            out["emails"] = sorted(found, key=rank)[:6]
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        finally:
            await ctx.close()
        return v["name"], out


async def main(names: list[str]) -> None:
    from playwright.async_api import async_playwright
    venues = json.loads((HERE / "venues.json").read_text())["venues"]
    pick = [v for v in venues if any(n.lower() in v["name"].lower() for n in names)]
    sem = asyncio.Semaphore(6)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        results = dict(await asyncio.gather(*[one(browser, v, sem) for v in pick]))
        await browser.close()
    Path("contacts.json").write_text(json.dumps(results, indent=1) + "\n")
    for n, r in results.items():
        print(f"{n}: {', '.join(r['emails']) or '-'} {r['error'] or ''}")


if __name__ == "__main__":
    asyncio.run(main([s.strip() for s in sys.argv[1].split(",") if s.strip()]))
