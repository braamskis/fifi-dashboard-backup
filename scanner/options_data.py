"""
Options checks for scan passers, from Yahoo option chains (end of day).

For each ticker: tradeability (open interest, ATM bid/ask spread, weekly expirations),
ATM implied volatility vs 20-day realized volatility, IV rank (built from our own
nightly IV history, so it needs ~20 scans before it shows), and unusual activity:
contracts trading well above their open interest with real premium behind them.

Limits worth knowing: this is an end-of-day snapshot, and Yahoo does not say whether
a print was bought or sold, so "unusual" means unusually active, not necessarily bullish
for calls / bearish for puts. Treat it as a flag to look closer, not a signal.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

MAX_DTE = 45            # look at expirations out to ~6 weeks
MAX_EXPIRIES = 4
UOA_MIN_VOL = 500       # contracts
UOA_VOL_OI = 2.0        # volume at least 2x open interest
UOA_MIN_PREM = 100_000  # dollars


def realized_vol(closes: np.ndarray, n: int = 20) -> float:
    r = np.diff(np.log(closes[-n - 1:]))
    return float(np.std(r, ddof=1) * np.sqrt(252)) if len(r) > 2 else float("nan")


def _chain_stats(calls: pd.DataFrame, puts: pd.DataFrame, exp: str, dte: int, price: float):
    out = dict(oi=0.0, vol=0.0, cprem=0.0, pprem=0.0, unusual=[])
    for kind, df in (("C", calls), ("P", puts)):
        if df is None or df.empty:
            continue
        df = df.fillna(0)
        prem = df["volume"] * df["lastPrice"] * 100
        out["oi"] += float(df["openInterest"].sum())
        out["vol"] += float(df["volume"].sum())
        out["cprem" if kind == "C" else "pprem"] += float(prem.sum())
        hot = df[(df["volume"] >= UOA_MIN_VOL)
                 & (df["volume"] >= UOA_VOL_OI * df["openInterest"].clip(lower=1))
                 & (prem >= UOA_MIN_PREM)]
        for _, r in hot.iterrows():
            out["unusual"].append(dict(
                k=kind, strike=float(r["strike"]), exp=exp, dte=int(dte), vol=int(r["volume"]),
                oi=int(r["openInterest"]), prem=round(float(r["volume"] * r["lastPrice"] * 100)),
                otm=round((r["strike"] / price - 1) * 100, 1)))
    return out


def _atm(calls: pd.DataFrame, puts: pd.DataFrame, price: float):
    ivs, spreads = [], []
    for df in (calls, puts):
        if df is None or df.empty:
            continue
        r = df.iloc[(df["strike"] - price).abs().argsort()[:1]].iloc[0]
        iv = float(r.get("impliedVolatility") or 0)
        if 0.05 <= iv <= 5:
            ivs.append(iv)
        bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
        mid = (bid + ask) / 2
        if mid > 0 and ask >= bid:
            spreads.append((ask - bid) / mid)
    return (float(np.mean(ivs)) if ivs else None, float(np.mean(spreads)) if spreads else None)


def snapshot(ticker: str, price: float, closes: np.ndarray, as_of: str) -> dict:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    try:
        exps = list(tk.options)
    except Exception:
        exps = []
    if not exps:
        return dict(has=False)
    today = pd.Timestamp(as_of)
    dated = [(e, (pd.Timestamp(e) - today).days) for e in exps]
    near = [(e, d) for e, d in dated if 0 <= d <= MAX_DTE][:MAX_EXPIRIES]
    weekly = sum(1 for _, d in dated if 0 <= d <= 21) >= 3
    tot = dict(oi=0.0, vol=0.0, cprem=0.0, pprem=0.0, unusual=[])
    iv = spread = None
    for e, d in near:
        try:
            ch = tk.option_chain(e)
        except Exception:
            continue
        st = _chain_stats(ch.calls, ch.puts, e, d, price)
        for k in ("oi", "vol", "cprem", "pprem"):
            tot[k] += st[k]
        tot["unusual"] += st["unusual"]
        if iv is None and d >= 7:
            iv, spread = _atm(ch.calls, ch.puts, price)
        time.sleep(0.25)
    return summarize(tot, iv, spread, weekly, realized_vol(closes))


def summarize(tot: dict, iv, spread, weekly: bool, hv: float) -> dict:
    unusual = sorted(tot["unusual"], key=lambda u: u["prem"], reverse=True)[:4]
    prem = tot["cprem"] + tot["pprem"]
    return dict(
        has=True,
        iv=round(iv * 100, 1) if iv else None,
        hv=round(hv * 100, 1) if np.isfinite(hv) else None,
        ivhv=round(iv / hv, 2) if iv and np.isfinite(hv) and hv > 0 else None,
        oi=int(tot["oi"]), vol=int(tot["vol"]),
        spread=round(spread * 100, 1) if spread is not None else None,
        weekly=bool(weekly),
        call_share=round(tot["cprem"] / prem, 2) if prem else None,
        unusual=unusual,
    )


def classify(o: dict, side: str) -> list[str]:
    """Badges: OPT = easy to trade, THIN = hard to trade, UOA = unusual activity on your side."""
    if not o or not o.get("has"):
        return ["THIN"]
    badges = []
    if o["oi"] >= 5000 and (o["spread"] or 99) <= 10 and o["weekly"]:
        badges.append("OPT")
    elif o["oi"] < 1000 or (o["spread"] or 99) > 25:
        badges.append("THIN")
    want = "C" if side == "long" else "P"
    mine = sum(u["prem"] for u in o["unusual"] if u["k"] == want)
    other = sum(u["prem"] for u in o["unusual"] if u["k"] != want)
    if mine and mine >= other:
        badges.append("UOA")
    return badges


# ------------------------------------------------------------------ IV rank history
def load_iv_history(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def update_iv_rank(hist: dict, ticker: str, as_of: str, o: dict) -> None:
    """Append today's ATM IV and compute IV rank over the stored window (up to a year)."""
    if not o.get("iv"):
        o["ivr"], o["ivr_n"] = None, len(hist.get(ticker, []))
        return
    series = [p for p in hist.get(ticker, []) if p[0] != as_of] + [[as_of, o["iv"]]]
    series = series[-252:]
    hist[ticker] = series
    vals = [p[1] for p in series]
    o["ivr_n"] = len(vals)
    lo, hi = min(vals), max(vals)
    o["ivr"] = round((o["iv"] - lo) / (hi - lo) * 100) if len(vals) >= 20 and hi > lo else None


def save_iv_history(path: Path, hist: dict, keep: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # drop tickers that have not been seen for a while to keep the file small
    cutoff = sorted({p[-1][0] for p in hist.values() if p})[-60:][:1]
    trimmed = {t: s for t, s in hist.items() if t in keep or (s and cutoff and s[-1][0] >= cutoff[0])}
    path.write_text(json.dumps(trimmed, separators=(",", ":")))
