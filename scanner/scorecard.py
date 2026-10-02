"""
Scan scorecard: did the setups work?

Every scan is saved as a slim dated file (site/history/YYYY-MM-DD.json). Each night
the scorecard replays what happened after each saved setup, using the same price
data the scan already downloaded:

  triggered   price reached the pivot (long) / trigger (short) within 10 sessions
  entry       the pivot, or the open if it gapped through
  result R    exit at the stop (or the open, if it gapped through the stop), else the
              close 20 sessions after entry; in multiples of the entry-to-stop risk
  2R          reached 2x risk in the trader's favor at any point
  10d         % move from the scan-day close to 10 sessions later, in the setup's direction

Stats are grouped by side, grade and pattern. `--backfill N` rebuilds the last N
trading days of scans from price history so the scorecard is useful on day one.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

TRIGGER_WINDOW = 10
HOLD = 20
PATTERNS = ("VCP", "FLAG", "HTF", "WBO", "WPV", "WVCP", "WFLAG", "3WT")


def slim(data: dict) -> dict:
    keep = ("t", "side", "grade", "score", "rs", "price", "badges")
    out = {"as_of": data["as_of"]}
    for side in ("long", "short"):
        out[side] = [{**{k: s[k] for k in keep}, "pivot": s["levels"]["pivot"], "stop": s["levels"]["stop"]}
                     for s in data.get(side, [])]
    return out


def write_history(folder: Path, data: dict, overwrite: bool = True) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{data['as_of']}.json"
    if overwrite or not p.exists():
        p.write_text(json.dumps(slim(data), separators=(",", ":")))


def _outcome(e: dict, side: str, post: pd.DataFrame) -> dict:
    o, h, l, c = (post[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    long = side == "long"
    piv, stop, price = e["pivot"], e["stop"], e["price"]
    res = dict(trig=False, r=None, hit2=False, done=False, ret10=None)
    if len(c) >= 10:
        res["ret10"] = round((c[9] / price - 1) * (1 if long else -1) * 100, 2)
    for i in range(min(TRIGGER_WINDOW, len(c))):
        hit = h[i] >= piv if long else l[i] <= piv
        if not hit:
            continue
        entry = max(piv, o[i]) if long else min(piv, o[i])
        risk = (entry - stop) if long else (stop - entry)
        if risk <= 0:
            return res                      # gapped past the stop: no trade
        res["trig"] = True
        end = min(len(c), i + HOLD)
        for j in range(i, end):
            if long and h[j] >= entry + 2 * risk or not long and l[j] <= entry - 2 * risk:
                res["hit2"] = True
            stopped = l[j] <= stop if long else h[j] >= stop
            if stopped:
                gap_exit = (j > i) and (o[j] < stop if long else o[j] > stop)
                exit_ = o[j] if gap_exit else stop
                res["r"] = round(((exit_ - entry) if long else (entry - exit_)) / risk, 2)
                res["done"] = True
                return res
        exit_ = c[end - 1]
        res["r"] = round(((exit_ - entry) if long else (entry - exit_)) / risk, 2)
        res["done"] = end - i >= HOLD
        return res
    res["done"] = len(c) >= TRIGGER_WINDOW
    return res


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    trig = [r for r in rows if r["trig"]]
    rs = [r["r"] for r in trig if r["r"] is not None]
    r10 = [r["ret10"] for r in rows if r["ret10"] is not None]
    return dict(
        n=n, trig=round(len(trig) / n * 100) if n else 0,
        win=round(sum(x > 0 for x in rs) / len(rs) * 100) if rs else None,
        avg_r=round(float(np.mean(rs)), 2) if rs else None,
        hit2=round(sum(r["hit2"] for r in trig) / len(trig) * 100) if trig else None,
        ret10=round(float(np.mean(r10)), 2) if r10 else None,
    )


def evaluate(folder: Path, frames: dict[str, pd.DataFrame], days: int = 90) -> dict:
    files = sorted(folder.glob("*.json"))[-days:] if folder.exists() else []
    results = {"long": [], "short": []}
    recent = []
    for f in files:
        snap = json.loads(f.read_text())
        d = pd.Timestamp(snap["as_of"])
        for side in ("long", "short"):
            for e in snap.get(side, []):
                df = frames.get(e["t"])
                if df is None:
                    continue
                post = df[df.index > d].iloc[:TRIGGER_WINDOW + HOLD]
                if post.empty:
                    continue
                res = _outcome(e, side, post)
                pats = [b for b in e["badges"] if b in PATTERNS] or ["No pattern"]
                row = dict(**res, grade=e["grade"], pats=pats)
                results[side].append(row)
                if res["trig"]:
                    recent.append(dict(date=snap["as_of"], t=e["t"], side=side, grade=e["grade"],
                                       pats=pats, r=res["r"], hit2=res["hit2"], done=res["done"]))
    out = {"since": files[0].stem if files else None, "scans": len(files)}
    for side, rows in results.items():
        grades = ["A+", "A", "B", "C", "D", "F"]
        out[side] = dict(
            all=_agg(rows),
            by_grade=[dict(key=g, **_agg([r for r in rows if r["grade"] == g])) for g in grades
                      if any(r["grade"] == g for r in rows)],
            by_pattern=[dict(key=p, **_agg([r for r in rows if p in r["pats"]]))
                        for p in (*PATTERNS, "No pattern") if any(p in r["pats"] for r in rows)],
        )
    out["recent"] = sorted(recent, key=lambda r: r["date"], reverse=True)[:25]
    return out
