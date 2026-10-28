-- Word NYC stats (Cloudflare D1). Only daily totals: no IDs, no IP addresses, nothing per person.
-- Safe to run again: every statement is idempotent.

-- Daily totals. metric: open, tix, stix, spv, spt, fav, unfav, share (see stats/worker.js)
-- plat: app | web. k: venue slug for venue metrics, the source for opens, '' otherwise.
-- n: how many times; firsts: for metric 'open', how many were the first open of that day on a device.
CREATE TABLE IF NOT EXISTS counts (
  day TEXT NOT NULL,
  metric TEXT NOT NULL,
  plat TEXT NOT NULL,
  k TEXT NOT NULL DEFAULT '',
  n INTEGER NOT NULL DEFAULT 0,
  firsts INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, metric, plat, k)
);

-- Current followers per venue (follows minus unfollows).
CREATE TABLE IF NOT EXISTS followers (
  venue TEXT PRIMARY KEY,
  n INTEGER NOT NULL DEFAULT 0
);

-- Noon notifications, reported by scraper/notify.py from OneSignal's delivery stats.
CREATE TABLE IF NOT EXISTS pushes (
  id TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'base',
  sponsor TEXT NOT NULL DEFAULT '',
  fav TEXT NOT NULL DEFAULT '',
  sent INTEGER NOT NULL DEFAULT 0,
  opened INTEGER NOT NULL DEFAULT 0,
  ios INTEGER NOT NULL DEFAULT 0,
  updated TEXT
);
CREATE INDEX IF NOT EXISTS pushes_day ON pushes(day);
