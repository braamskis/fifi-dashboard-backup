#!/usr/bin/env python3
"""
Intraday pivot alerts for the best setups on tonight's scan.

Runs every 10 minutes during market hours (GitHub Actions, see .github/workflows/alerts.yml).
Watches A+ and A grades plus anything with a setup badge, on both sides:

  long   the day's high reaches the pivot and price is still within 0.5% of it
  short  the day's low reaches the trigger and price is still within 0.5% of it

Each ticker alerts once per day and side. Alerts go to a Discord channel if the
DISCORD_WEBHOOK_URL secret is set (Discord pushes them to your phone), and are always
written to site/alerts.json, which the dashboard reads to mark TRG rows.

Volume pace = volume so far vs the 50-day average scaled to the time of day; 1.5x+
is what you want on a real breakout.

Yahoo intraday data can lag a few minutes, and GitHub can start scheduled runs late
at busy times, so treat these as "go look now" pings, not execution signals.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")
SETUPS = {"VCP", "FLAG", "HTF", "WBO", "WPV", "WVCP", "WFLAG", "3WT"}
MAX_TICKERS = 80


def candidates(data: dict) -> list[dict]:
    out = []
    for side in ("long", "short"):
        for r in data.get(side, []):
            if r["grade"] in ("A+", "A") or SETUPS & set(r["badges"]):
                out.append(r)
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:MAX_TICKERS]


def session_fraction(now: dt.datetime) -> float:
    open_ = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return min(1.0, max(0.02, (now - open_).total_seconds() / (390 * 60)))


def check(rows: list[dict], intraday: dict[str, pd.DataFrame], fired: set, now: dt.datetime) -> list[dict]:
    new = []
    frac = session_fraction(now)
    for r in rows:
        key = f"{r['t']}:{r['side']}"
        df = intraday.get(r["t"])
        if key in fired or df is None or df.empty:
            continue
        hi, lo, last = float(df["High"].max()), float(df["Low"].min()), float(df["Close"].iloc[-1])
        vol = float(df["Volume"].sum())
        level = r["levels"]["pivot"]
        hit = (hi >= level and last >= level * 0.995) if r["side"] == "long" else (lo <= level and last <= level * 1.005)
        if not hit:
            continue
        pace = vol / (r.get("avgv") or 1) / frac if r.get("avgv") else None
        new.append(dict(t=r["t"], side=r["side"], grade=r["grade"], level=level, price=round(last, 2),
                        stop=r["levels"]["stop"], pace=round(pace, 2) if pace else None,
                        setups=[b for b in r["badges"] if b in SETUPS],
                        time=now.strftime("%H:%M")))
    return new


def discord(alerts: list[dict], url: str) -> None:
    for a in alerts:
        up = a["side"] == "long"
        title = f"{'🟢' if up else '🔴'} {a['t']} {'through pivot' if up else 'through trigger'} ${a['level']}"
        risk = abs(a["price"] - a["stop"]) / a["price"] * 100
        desc = (f"Last ${a['price']} · stop ${a['stop']} ({risk:.1f}% risk) · grade {a['grade']}"
                + (f" · {' '.join(a['setups'])}" if a["setups"] else "")
                + (f"\nVolume pace {a['pace']}x" if a["pace"] else ""))
        body = json.dumps({"embeds": [{
            "title": title, "description": desc, "color": 0x00E676 if up else 0xFF5252,
            "url": f"https://www.tradingview.com/chart/?symbol={a['t'].replace('-', '.')}",
        }]}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                              "User-Agent": "FiFi's Dashboard"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except Exception as e:
            print(f"  discord post failed for {a['t']}: {e}", file=sys.stderr)


def fetch_intraday(tickers: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    df = yf.download(tickers, period="1d", interval="5m", group_by="ticker", auto_adjust=False,
                     prepost=False, threads=True, progress=False)
    out = {}
    multi = isinstance(df.columns, pd.MultiIndex)
    for t in tickers:
        try:
            sub = df[t] if multi else df
            out[t] = sub.dropna(subset=["Close"])
        except KeyError:
            pass
    return out


def main() -> None:
    force = "--force" in sys.argv
    now = dt.datetime.now(ET)
    if not force and (now.weekday() >= 5 or not (dt.time(9, 35) <= now.time() <= dt.time(16, 0))):
        print("Market closed. Nothing to check.")
        return
    site = Path("site")
    data = json.loads((site / "scan.json").read_text())
    rows = candidates(data)
    state_p = site / "alerts.json"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    today = now.date().isoformat()
    if state.get("date") != today:
        state = {"date": today, "fired": []}
    fired = {f"{a['t']}:{a['side']}" for a in state["fired"]}
    new = check(rows, fetch_intraday(sorted({r["t"] for r in rows})), fired, now)
    if not new:
        print(f"{now:%H:%M} ET: {len(rows)} setups watched, nothing triggered.")
        return
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url:
        discord(new, url)
    state["fired"] += new
    state_p.write_text(json.dumps(state, separators=(",", ":")))
    print(f"{now:%H:%M} ET: triggered {', '.join(a['t'] + ' ' + a['side'] for a in new)}")


if __name__ == "__main__":
    main()
