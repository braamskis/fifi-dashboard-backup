#!/usr/bin/env python3
"""
Relative Rotation Graph (RRG) data for the dashboard.

Plots each US sector against the benchmark on two axes, the way StockCharts RRG does:

  RS-Ratio     relative strength vs SPY, normalized so 100 is neutral.
                 >100 = outperforming.
  RS-Momentum  the rate of change of RS-Ratio, also centered on 100.
                 >100 = relative strength is still improving.

Quadrants: Leading (right/top), Weakening (right/bottom), Lagging (left/bottom),
Improving (left/top). Sectors normally rotate clockwise through them.

Weekly points, with a tail of the last 12 weeks. Written to site/rrg.json.

  python scanner/rrg.py --out site/rrg.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

BENCH = "SPY"
# The 11 US sector SPDRs. Add ETFs here if you ever want more on the graph.
SECTORS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care",
    "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
    "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate",
    "XLC": "Communication Services",
}
TAIL = 12          # weeks shown
Z_N = 26           # window everything is normalized over (weeks)
MOM_N = 4          # lookback for relative-strength momentum (weeks)
SMOOTH = 5         # smoothing of the relative strength line, so tails curve instead of zigzag


def _z(s: pd.Series, n: int) -> pd.Series:
    """Standard score over a rolling window. A flat series scores 0, not NaN."""
    m, sd = s.rolling(n).mean(), s.rolling(n).std(ddof=0)
    return ((s - m) / sd).where(sd > 1e-12, 0.0)


def rrg_points(close: pd.Series, bench: pd.Series) -> list[dict]:
    """Weekly (date, RS-Ratio, RS-Momentum) for one ticker against the benchmark."""
    wk = pd.DataFrame({"c": close, "b": bench}).resample("W-FRI").last().dropna()
    if len(wk) < Z_N + MOM_N + TAIL:
        return []
    rs = (100 * wk["c"] / wk["b"]).ewm(span=SMOOTH, adjust=False).mean()
    ratio = 100 + _z(rs, Z_N)                          # how far RS sits above its own trend
    mom = 100 + _z(rs.pct_change(MOM_N).ewm(span=SMOOTH, adjust=False).mean(), Z_N)
    out = pd.DataFrame({"ratio": ratio, "mom": mom}).dropna().tail(TAIL)
    return [dict(d=str(i.date()), x=round(float(r.ratio), 2), y=round(float(r.mom), 2))
            for i, r in out.iterrows()]


def quadrant(x: float, y: float) -> str:
    if x >= 100:
        return "Leading" if y >= 100 else "Weakening"
    return "Improving" if y >= 100 else "Lagging"


def build(frames: dict[str, pd.Series]) -> dict:
    bench = frames[BENCH]
    items = []
    for t, name in SECTORS.items():
        if t not in frames:
            continue
        pts = rrg_points(frames[t], bench)
        if not pts:
            continue
        last = pts[-1]
        items.append(dict(t=t, name=name, tail=pts, quadrant=quadrant(last["x"], last["y"])))
    items.sort(key=lambda i: i["tail"][-1]["x"], reverse=True)
    return dict(bench=BENCH, weeks=TAIL,
                as_of=max((i["tail"][-1]["d"] for i in items), default=None),
                generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                items=items)


def fetch(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf
    df = yf.download(tickers, period="3y", interval="1d", auto_adjust=True,
                     group_by="ticker", threads=True, progress=False)
    out = {}
    multi = isinstance(df.columns, pd.MultiIndex)
    for t in tickers:
        try:
            s = (df[t] if multi else df)["Close"].dropna()
        except KeyError:
            continue
        if len(s) > 200:
            out[t] = s
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="site/rrg.json")
    a = ap.parse_args()
    frames = fetch([BENCH] + list(SECTORS))
    if BENCH not in frames:
        raise SystemExit(f"No {BENCH} data; skipping RRG.")
    data = build(frames)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(data, separators=(",", ":")))
    print(f"RRG {data['as_of']}: " + ", ".join(f"{i['t']} {i['quadrant']}" for i in data["items"]))


if __name__ == "__main__":
    main()
