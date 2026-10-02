"""
Daily bars from Massive (formerly Polygon.io).

One request per trading day returns every US stock's bar for that day
(GET /v2/aggs/grouped/locale/us/market/stocks/{date}), so a full two-year history
for the whole market is ~500 calls instead of one call per ticker. Split-adjusted.

The key lives in the MASSIVE_API_KEY environment variable (a GitHub Actions secret)
and is sent as a bearer token, never in a URL. Without the key, or if the API fails,
the scan falls back to Yahoo (see universe.download).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

import pandas as pd

HOSTS = ["https://api.massive.com", "https://api.polygon.io"]   # old host still works
GROUPED = "/v2/aggs/grouped/locale/us/market/stocks/{date}?adjusted=true"
MAX_EMPTY = 12          # consecutive empty days before we assume something is wrong


def api_key() -> str | None:
    return os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")


def _get(path: str, key: str, tries: int = 4) -> dict | None:
    """GET a Massive endpoint, retrying on rate limits and transient errors."""
    for attempt in range(tries):
        for host in HOSTS:
            req = urllib.request.Request(
                host + path,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json",
                         "User-Agent": "FiFi Dashboard"})
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    break                      # back off, then retry the same host
                if e.code in (401, 403):
                    raise RuntimeError(f"Massive rejected the API key ({e.code}). "
                                       "Check the MASSIVE_API_KEY secret and the plan.") from e
                if e.code == 404:
                    return None
            except Exception as e:             # DNS, timeout, unknown host: try the next host
                print(f"  massive {host}: {e}", file=sys.stderr)
        time.sleep(2 * (attempt + 1))
    return None


def grouped_day(date: str, key: str) -> list[dict]:
    data = _get(GROUPED.format(date=date), key)
    return (data or {}).get("results") or []


def download(tickers: list[str], days: int = 520, key: str | None = None,
             progress_every: int = 50) -> dict[str, pd.DataFrame]:
    """Daily bars for `tickers` over the last `days` trading days, oldest first.

    Walks back over calendar days; weekends and holidays come back empty and are skipped."""
    key = key or api_key()
    if not key:
        raise RuntimeError("No MASSIVE_API_KEY set.")
    keep = set(tickers)
    rows: dict[str, list[tuple]] = {}
    day = dt.date.today()
    got = empty = 0
    while got < days:
        if day.weekday() < 5:
            results = grouped_day(day.isoformat(), key)
            if results:
                for r in results:
                    t = r.get("T")
                    if t in keep and r.get("c"):
                        rows.setdefault(t, []).append(
                            (day, r.get("o"), r.get("h"), r.get("l"), r.get("c"), r.get("v") or 0))
                got += 1
                empty = 0
                if got % progress_every == 0:
                    print(f"  massive: {got}/{days} trading days, {len(rows)} tickers")
            else:
                empty += 1
                if empty >= MAX_EMPTY:
                    raise RuntimeError(f"Massive returned no data for {empty} days in a row "
                                       f"(last tried {day}). Check the plan history limit.")
        day -= dt.timedelta(days=1)
    frames = {}
    for t, rs in rows.items():
        df = pd.DataFrame(rs, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        df = df.dropna().drop_duplicates(subset="Date").sort_values("Date")
        df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("Date")))
        frames[t] = df.astype(float)
    print(f"  massive: {len(frames)} tickers over {got} trading days")
    return frames
