#!/usr/bin/env python3
"""
FiFi's Dashboard: nightly long and short scan of the whole US market.

  python scanner/scan.py                          full market, writes site/scan.json + site/charts/
  python scanner/scan.py --backfill 60            also rebuild 60 days of past scans for the scorecard
  python scanner/scan.py --universe list.txt      only your list
  python scanner/scan.py --demo                   synthetic data, offline (tests everything)

Long list:  Minervini trend template + RS 70, or a weekly setup in stage 2 with RS 60.
Short list: the same rules on the inverted chart (stage 4, RS 30 or lower).
Each stock gets setup badges, RS, stage, group strength, key levels, options
checks and a TQE grade. See README.md for every rule.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import core
import options_data as opt
import scorecard as sc
from core import INVERT_K, MIN_BARS, grade, invert, key_levels, metrics
from universe import fetch_meta, full_market_universe, read_list

# ------------------------------------------------------------------ settings
MIN_PRICE = 10.0
MIN_DOLLAR_VOL = 20e6
MIN_RS = 70
WEEKLY_MIN_RS = 60
MARKET = ["SPY", "QQQ", "IWM"]
ENRICH_LIMIT = 120        # earnings lookups per side
OPTIONS_LIMIT = 80        # option-chain checks per side (top by grade)
DATA = Path(__file__).parent / "data"

# code: (description, colour group). Short-side codes mirror the long ones.
BADGES = {
    "VCP":   ("VCP. Long: pullbacks getting shallower under a pivot. Short: bounces getting smaller over a breakdown level", "setup"),
    "FLAG":  ("Tight flag. Long: 30%+ run then a tight flag. Short: sharp drop then a tight bear flag", "setup"),
    "HTF":   ("High tight flag: 90%+ run in 8 weeks or less, then a flag under 25% deep", "setup"),
    "WBO":   ("Weekly breakout: this week is closing through the weekly pivot on above-average volume", "setup"),
    "WPV":   ("At the weekly pivot: strong week pressing the right-side high of a weekly base, not through yet", "setup"),
    "WVCP":  ("Weekly VCP: contractions getting tighter on the weekly chart", "setup"),
    "WFLAG": ("Weekly flag: big run, then a tight 2-10 week flag", "setup"),
    "3WT":   ("3 weeks tight: last 3 weekly closes within 1.5%", "tight"),
    "NR7":   ("Narrowest daily range of the last 7 sessions", "tight"),
    "ID":    ("Inside day", "tight"),
    "RSBP":  ("RS line at a new high before price. Short: RS new low before price", "method"),
    "RSNH":  ("RS line (vs SPY) at a 52-week high. Short: 52-week low", "method"),
    "KQ":    ("Qullamaggie momentum leader: top 7% gainer (1/3/6 mo), ADR 4%+, near highs", "method"),
    "ON":    ("O'Neil-style leader (technical only): RS 80+, within 15% of high, 50 > 200", "method"),
    "97C":   ("97 Club: RS rank 97 or higher", "method"),
    "LG":    ("Leading group: industry in the top 20% by RS", "group"),
    "WG":    ("Weak group: industry in the bottom 20% by RS", "group"),
    "EMA":   ("TQE EMA stack. Long: price > 8 > 21 > 50 EMA. Short: price < 8 < 21 < 50", "tqe"),
    "SB4":   ("Stockbee burst: up 4%+ today on higher volume", "burst"),
    "SBW":   ("Up 20%+ in 5 sessions", "burst"),
    "PP":    ("Pocket pivot: up day on volume above any down day of the last 10, above the 50 SMA", "burst"),
    "SD4":   ("Down 4%+ today on higher volume", "burst"),
    "SDW":   ("Down 17%+ in 5 sessions", "burst"),
    "DV":    ("Down day on volume above any up day of the last 10, below the 50 SMA", "burst"),
    "9M":    ("9M+ shares traded today", "liquidity"),
    "HV":    ("Highest volume in a year", "liquidity"),
    "LQ":    ("Liquid leader: $100M+/day and up 30%+ in 6 months", "liquidity"),
    "OPT":   ("Options easy to trade: 5K+ open interest, ATM spread 10% or less, weekly expirations", "liquidity"),
    "52W":   ("New 52-week high today", "structure"),
    "52L":   ("New 52-week low today", "structure"),
    "DB":    ("Darvas box breakout in the last 5 sessions, still above the box", "structure"),
    "BD":    ("Box breakdown in the last 5 sessions, still below the box", "structure"),
    "UOA":   ("Unusual options activity on your side (calls for longs, puts for shorts). Side of the trade unknown", "event"),
    "ER-1":  ("Reported earnings in the last session", "event"),
    "NEW":   ("First day on the scan", "event"),
    "TRG":   ("Triggered today: price crossed the pivot / trigger during the session", "event"),
    "ER+":   ("Earnings within 7 days: size down or wait", "risk"),
    "EXT":   ("Extended: 7+ ADRs from the 50 SMA, wait for a pullback", "risk"),
    "THIN":  ("Options hard to trade: little open interest or wide spreads", "risk"),
    "WL":    ("On your watchlist", "watch"),
}
BADGE_ORDER = list(BADGES)
LONG_ONLY = {"SB4": "SD4", "SBW": "SDW", "PP": "DV", "52W": "52L", "DB": "BD"}   # long code -> short code
STAGE_SHORT = {"2A": "4A", "2B": "4B", "1": "3", "3": "1", "4": "2"}


# ------------------------------------------------------------------ helpers
def _pct_rank(x: float, arr: np.ndarray) -> float:
    return float(np.searchsorted(arr, x, side="right") / len(arr)) if len(arr) and np.isfinite(x) else 0.0


def _rs(weighted: float, ref: np.ndarray) -> int:
    return max(1, min(99, math.ceil(_pct_rank(weighted, ref) * 99)))


def _weighted(m: dict, short: bool = False) -> float:
    rs = [m["r63"], m["r126"], m["r189"], m["r252"]]
    if short:                                  # returns on the inverted chart
        rs = [1 / (1 + r) - 1 if np.isfinite(r) and r > -1 else float("nan") for r in rs]
    return 0.4 * rs[0] + 0.2 * rs[1] + 0.2 * rs[2] + 0.2 * rs[3]


def _flip(p: float) -> float:
    return INVERT_K / p


def describe(m: dict, side: str, dates: list[str]) -> tuple[list[str], list[dict]]:
    """Setup text and chart markers, written for the side being traded."""
    txt, marks = [], []
    long = side == "long"
    up, dn = ("aboveBar", "arrowDown"), ("belowBar", "arrowUp")
    if m["vcp"]:
        v = m["vcp"]
        depths = v["depths"] if long else [round(d / (100 - d) * 100) for d in v["depths"]]
        txt.append(f"{'VCP' if long else 'Bear VCP'} {v['t']}T over {v['weeks']} wks: "
                   + ("pullbacks " if long else "bounces ") + " / ".join(f"{d}%" for d in depths))
        for k, ((hi_i, _, lo_i, _), d) in enumerate(zip(v["points"], depths), 1):
            a, b = (up, dn) if long else (dn, up)
            marks.append(dict(time=dates[hi_i], position=a[0], shape=a[1], text=f"T{k}"))
            marks.append(dict(time=dates[lo_i], position=b[0], shape=b[1], text=f"{'-' if long else '+'}{d}%"))
    if m["flag"]:
        f = m["flag"]
        if long:
            name = "High tight flag" if f["kind"] == "HTF" else "Flag"
            txt.append(f"{name}: +{f['run']}% in {f['run_days']} days, then {f['days']} days and {f['depth']}% deep")
            marks.append(dict(time=dates[f["lo_i"]], position=dn[0], shape=dn[1], text=f"run +{f['run']}%"))
            marks.append(dict(time=dates[f["top_i"]], position=up[0], shape=up[1], text="flag top"))
        else:
            drop = round((1 - 1 / (1 + f["run"] / 100)) * 100)
            bounce = round(f["depth"] / (100 - f["depth"]) * 100)
            txt.append(f"Bear flag: -{drop}% in {f['run_days']} days, then {f['days']} days, bounce {bounce}%")
            marks.append(dict(time=dates[f["lo_i"]], position=up[0], shape=up[1], text=f"drop -{drop}%"))
            marks.append(dict(time=dates[f["top_i"]], position=dn[0], shape=dn[1], text="flag low"))
    w = m.get("weekly")
    if w:
        kinds = [k for k in ("WBO", "WPV") if w[k]] + (["WVCP"] if w["WVCP"] else []) + (["WFLAG"] if w["WFLAG"] else [])
        label = {"WBO": "weekly breakout" if long else "weekly breakdown",
                 "WPV": "pressing the weekly pivot" if long else "pressing the weekly breakdown level",
                 "WVCP": "weekly VCP", "WFLAG": "weekly flag"}
        extra = ""
        if w["WBO"] or w["WPV"]:
            extra = f". Base {w['base_weeks']} weeks, {w['depth']}% deep"
            if w["pace"]:
                extra += f", volume pace {w['pace']}x the 10-week average"
        txt.append(f"Weekly: {', '.join(label[k] for k in kinds)}{extra}")
    return txt, marks


def chart_file(df: pd.DataFrame, row: dict, marks: list[dict], bench: pd.Series | None) -> dict:
    """Per-ticker chart data: a year of daily bars, two years of weekly bars, EMAs / weekly
    MAs, the RS line, pattern markers and the key levels."""
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    c = df["Close"].to_numpy(float)
    emas = [core._ema(c, n) for n in (8, 21, 50)]
    tail = df.iloc[-260:]
    k = len(tail)
    times = [str(pd.Timestamp(d).date()) for d in tail.index]
    w = core.to_weekly(df)
    wc = w["Close"].to_numpy(float)
    wmas = [core._sma(wc, n) for n in (10, 20, 40)]
    wt = w.iloc[-104:]
    wtimes = [str(pd.Timestamp(d).date()) for d in wt.index]
    rs_d = rs_w = None
    if bench is not None:
        b = bench.reindex(df.index).ffill()
        rsl = (df["Close"] / b).to_numpy(float)
        rs_d = [round(float(x) * 100, 4) if np.isfinite(x) else None for x in rsl[-k:]]
        bw = b.resample("W-FRI").last().reindex(w.index)
        rsw = (w["Close"] / bw).to_numpy(float)
        rs_w = [round(float(x) * 100, 4) if np.isfinite(x) else None for x in rsw[-len(wt):]]
    L, lv = row["levels"], row["keylv"]
    lines = [dict(p=L["pivot"], t="Pivot" if row["side"] == "long" else "Trigger", c="#b8962e", s=2),
             dict(p=L["stop"], t="Stop", c="#ff5252", s=2),
             dict(p=lv["wo"], t="W open", c="#9aa7b8", s=3)]
    return dict(
        t=row["t"], side=row["side"],
        bars=[[tm, round(float(r.Open), 2), round(float(r.High), 2), round(float(r.Low), 2),
               round(float(r.Close), 2), int(r.Volume)] for tm, r in zip(times, tail.itertuples())],
        ema={str(n): [round(float(x), 2) for x in e[-k:]] for n, e in zip((8, 21, 50), emas)},
        wbars=[[tm, round(float(r.Open), 2), round(float(r.High), 2), round(float(r.Low), 2),
                round(float(r.Close), 2), int(r.Volume)] for tm, r in zip(wtimes, wt.itertuples())],
        wma={str(n): [round(float(x), 2) if np.isfinite(x) else None for x in m_[-len(wt):]]
             for n, m_ in zip((10, 20, 40), wmas)},
        rs=rs_d, wrs=rs_w,
        marks=[mk for mk in marks if mk["time"] >= times[0]],
        lines=lines,
    )


# ------------------------------------------------------------------ market context
def market_rows(frames: dict) -> list[dict]:
    out = []
    for t in MARKET:
        m = metrics(t, frames[t]) if t in frames else None
        if m:
            out.append(dict(t=t, price=round(m["price"], 2), chg1d=m["chg1d"], above21=m["above21"],
                            above50=m["above50"], above200=m["above200"], e21_gt_50=m["e21_gt_50"]))
    return out


def regime(market: list[dict], breadth50: float) -> dict:
    """Green / yellow / red from SPY and QQQ vs their 21 EMA and 50 SMA, plus breadth."""
    idx = [m for m in market if m["t"] in ("SPY", "QQQ")]
    pts = sum(m["above21"] + m["above50"] + m["e21_gt_50"] for m in idx)
    top = 3 * max(len(idx), 1)
    level = "green" if pts >= top - 1 else "yellow" if pts >= top / 2 else "red"
    if level == "green" and breadth50 < 0.40:
        level = "yellow"
    msg = {
        "green": "Uptrend. Longs favored, full size on A and A+ setups.",
        "yellow": "Mixed tape. Size down, take A+ longs only, shorts on the weakest groups.",
        "red": "Downtrend. Shorts favored. Longs only A+ and small.",
    }[level]
    return dict(level=level, text=msg, points=int(pts), max=int(top))


def industry_strength(feats: dict, meta: dict) -> dict[str, dict]:
    """Median RS of each industry's liquid stocks, ranked 1-99 against other industries."""
    groups: dict[str, list[int]] = {}
    for t, m in feats.items():
        ind = (meta.get(t) or {}).get("industry")
        if ind and m["liquid"]:
            groups.setdefault(ind, []).append(m["rs"])
    med = {g: float(np.median(v)) for g, v in groups.items() if len(v) >= 3}
    if not med:
        return {}
    arr = np.sort(np.array(list(med.values())))
    return {g: dict(rank=max(1, min(99, math.ceil(_pct_rank(x, arr) * 99))), n=len(groups[g]),
                    med=round(x)) for g, x in med.items()}


# ------------------------------------------------------------------ rows
def make_row(t: str, df: pd.DataFrame, mr: dict, mc: dict, side: str, ctx: dict) -> dict:
    """mr = metrics on the real chart, mc = metrics used for the setup (real for longs,
    inverted for shorts)."""
    long = side == "long"
    f = mc["flags"]
    meta = ctx["meta"].get(t) or {}
    grp = ctx["groups"].get(meta.get("industry") or "")
    badges = []
    for code in ("VCP", "FLAG", "HTF", "WBO", "WPV", "WVCP", "WFLAG", "3WT", "NR7", "ID",
                 "RSBP", "RSNH", "EMA", "SB4", "SBW", "PP", "52W", "DB", "EXT"):
        if f.get(code) and (long or code != "HTF"):
            badges.append(code if long else LONG_ONLY.get(code, code))
    for code in ("9M", "HV"):
        if mr["flags"][code]:
            badges.append(code)
    if long:
        if mc["top_gainer"] and mr["adr"] >= 4 and f["near20"]:
            badges.append("KQ")
        if mc["rs"] >= 80 and f["onbase"]:
            badges.append("ON")
        if mc["rs"] >= 97:
            badges.append("97C")
        if f["LQ"]:
            badges.append("LQ")
    bonus = 0
    if grp:
        if long:
            bonus = 5 if grp["rank"] >= 80 else -5 if grp["rank"] <= 30 else 0
            if grp["rank"] >= 80:
                badges.append("LG")
        else:
            bonus = 5 if grp["rank"] <= 20 else -5 if grp["rank"] >= 70 else 0
            if grp["rank"] <= 20:
                badges.append("WG")
    score, g = grade(mc, bonus)

    pivot = mc["pivot"] if long else _flip(mc["pivot"])
    stop = mc["stop"] if long else _flip(mc["stop"])
    price = mr["price"]
    risk = (price - stop) / price if long else (stop - price) / price
    lv = key_levels(df)
    if t in ctx["watch"]:
        badges.append("WL")
    prev = ctx["prev"].get(side, set())
    if prev and t not in prev and ctx["prev_asof"] != mr["date"]:
        badges.append("NEW")

    dates = [str(pd.Timestamp(d).date()) for d in df.dropna(subset=["Close"]).index]
    setup, marks = describe(mc, side, dates)
    d = df.dropna(subset=["Open", "High", "Low", "Close"])
    c = d["Close"].to_numpy(float)
    row = dict(
        t=t, side=side, x=ctx["exch"].get(t, ""), price=round(price, 2), chg1d=round(mr["chg1d"], 4),
        chg5d=round(mr["chg5d"], 4), adr=round(mr["adr"], 1), mcap=meta.get("mcap"),
        avgv=round(mr["avgv50"]), rs=mr["rs"], rsw=mc["rs"] if not long else None,
        stage=mr["stage"] if long else STAGE_SHORT.get(mc["stage"], mc["stage"]),
        tt=bool(mc["tt"]), score=score, grade=g, badges=badges, setup=setup,
        sector=meta.get("sector") or "", industry=meta.get("industry") or "",
        grp=grp,
        levels=dict(pivot=round(pivot, 2), ema21=round(mr["ema21"], 2), sma50=round(mr["sma50"], 2),
                    stop=round(stop, 2), stop_note=f"{mc['stop_note']} {'low' if long else 'high'}",
                    risk=round(risk, 4)),
        keylv=lv,
        ohlc=[[round(float(x), 2) for x in b] for b in d[["Open", "High", "Low", "Close"]].to_numpy()[-60:]],
        ema=[[round(float(x), 2) for x in core._ema(c, n)[-60:]] for n in (8, 21, 50)],
    )
    row["_marks"] = marks
    return row


# ------------------------------------------------------------------ build
def build(frames: dict[str, pd.DataFrame], ctx: dict, light: bool = False) -> tuple[dict, dict]:
    """light=True skips chart files and per-row extras (used for backfill)."""
    spy = frames.get("SPY")
    bench = spy["Close"] if spy is not None else None
    feats = {}
    for t, df in frames.items():
        if t in MARKET:
            continue
        m = metrics(t, df, bench)
        if not m:
            continue
        liquid = m["price"] >= MIN_PRICE and m["dvol50"] >= MIN_DOLLAR_VOL
        if liquid or t in ctx["watch"]:
            m["liquid"] = liquid
            feats[t] = m
    if not feats:
        raise SystemExit("No usable price data. Check the download step.")

    pool = [m for m in feats.values() if m["liquid"]]
    ref = np.sort(np.array([x for x in (_weighted(m) for m in pool) if np.isfinite(x)]))
    ref_s = np.sort(np.array([x for x in (_weighted(m, True) for m in pool) if np.isfinite(x)]))
    refs = {k: np.sort(np.array([m[k] for m in pool if np.isfinite(m[k])])) for k in ("r21", "r63", "r126")}
    for m in feats.values():
        m["rs"] = _rs(_weighted(m), ref)
        m["top_gainer"] = any(_pct_rank(m[k], refs[k]) >= 0.93 for k in ("r21", "r63", "r126"))
    ctx["groups"] = industry_strength(feats, ctx["meta"])
    as_of = max(m["date"] for m in feats.values())

    longs, shorts = [], []
    bench_inv = (INVERT_K / bench) if bench is not None else None
    for t, m in feats.items():
        wk = m["flags"]
        weekly_ok = (wk["WBO"] or wk["WPV"] or wk["WVCP"]) and m["stage"] in ("2A", "2B") and m["rs"] >= WEEKLY_MIN_RS
        if (m["tt"] and m["rs"] >= MIN_RS) or weekly_ok or (t in ctx["watch"] and m["tt"]):
            longs.append(make_row(t, frames[t], m, m, "long", ctx))
        # short candidates: below the 50 and the 200 on the real chart
        if not m["above50"] and not m["above200"]:
            mi = metrics(t, invert(frames[t]), bench_inv)
            if not mi:
                continue
            mi["rs"] = _rs(_weighted(m, True), ref_s)
            mi["top_gainer"] = False
            wi = mi["flags"]
            weekly_s = (wi["WBO"] or wi["WPV"] or wi["WVCP"]) and mi["stage"] in ("2A", "2B") and mi["rs"] >= WEEKLY_MIN_RS
            if (mi["tt"] and mi["rs"] >= MIN_RS) or weekly_s:
                shorts.append(make_row(t, frames[t], m, mi, "short", ctx))

    charts = {}
    for rows in (longs, shorts):
        rows.sort(key=lambda r: (r["score"], r["rs"] if r["side"] == "long" else -r["rs"]), reverse=True)
        for r in rows:
            marks = r.pop("_marks")
            if not light:
                charts[f"{r['t']}-{r['side']}"] = chart_file(frames[r["t"]], r, marks, bench)

    n = max(len(pool), 1)
    b50 = sum(m["above50"] for m in pool) / n
    market = market_rows(frames)
    ranked = sorted(ctx["groups"].items(), key=lambda kv: kv[1]["rank"], reverse=True)
    lc = pd.Series([r["industry"] for r in longs]).value_counts().to_dict() if longs else {}
    scnt = pd.Series([r["industry"] for r in shorts]).value_counts().to_dict() if shorts else {}
    data = dict(
        title="FiFi's Dashboard",
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        as_of=as_of, universe=len(frames), liquid=len(pool),
        passed=len(longs), passed_short=len(shorts),
        market=market,
        breadth=dict(above50=round(b50, 3), above200=round(sum(m["above200"] for m in pool) / n, 3),
                     new_highs=int(sum(m["newhigh"] for m in pool)), new_lows=int(sum(m["newlow"] for m in pool))),
        regime=regime(market, b50),
        groups=dict(
            top=[dict(name=g, **v, longs=int(lc.get(g, 0))) for g, v in ranked[:12]],
            bottom=[dict(name=g, **v, shorts=int(scnt.get(g, 0))) for g, v in ranked[::-1][:12]],
        ),
        legend={k: v[0] for k, v in BADGES.items()},
        groups_of={k: v[1] for k, v in BADGES.items()},
        long=longs, short=shorts,
    )
    return data, charts


# ------------------------------------------------------------------ enrichment
def add_earnings(rows: list[dict], as_of: str) -> None:
    import yfinance as yf
    asof = pd.Timestamp(as_of)
    for r in rows[:ENRICH_LIMIT]:
        try:
            ed = yf.Ticker(r["t"]).get_earnings_dates(limit=6)
            if ed is not None and len(ed):
                days = [(pd.Timestamp(d).tz_localize(None).normalize() - asof).days for d in ed.index]
                if any(-3 <= d <= 0 for d in days):
                    r["badges"].append("ER-1")
                if any(1 <= d <= 7 for d in days):
                    r["badges"].append("ER+")
        except Exception:
            pass
        time.sleep(0.3)


def add_options(rows: list[dict], frames: dict, as_of: str, iv_hist: dict, snap=None) -> None:
    snap = snap or opt.snapshot
    for r in rows[:OPTIONS_LIMIT]:
        closes = frames[r["t"]]["Close"].dropna().to_numpy(float)
        try:
            o = snap(r["t"], r["price"], closes, as_of)
        except Exception as e:
            print(f"  options {r['t']}: {e}", file=sys.stderr)
            continue
        opt.update_iv_rank(iv_hist, r["t"], as_of, o)
        r["options"] = o
        r["badges"] += opt.classify(o, r["side"])


def finish(data: dict) -> None:
    for side in ("long", "short"):
        for r in data[side]:
            r["badges"] = sorted(dict.fromkeys(r["badges"]), key=BADGE_ORDER.index)


# ------------------------------------------------------------------ backfill
def backfill(frames: dict, ctx: dict, days: int, folder: Path) -> None:
    """Rebuild past scans from price history so the scorecard has data immediately."""
    dates = frames["SPY"].index
    for k in range(days, 0, -1):
        cutoff = dates[-1 - k]
        p = folder / f"{cutoff.date()}.json"
        if p.exists():
            continue
        sub = {t: df[df.index <= cutoff] for t, df in frames.items()}
        sub = {t: df for t, df in sub.items() if len(df) >= MIN_BARS}
        data, _ = build(sub, {**ctx, "prev": {}, "prev_asof": None}, light=True)
        finish(data)
        sc.write_history(folder, data, overwrite=False)
        print(f"  backfilled {cutoff.date()}: {data['passed']} long / {data['passed_short']} short")


# ------------------------------------------------------------------ demo
def demo_world(seed: int = 7):
    """Synthetic market: leaders with VCPs / flags / a weekly pivot press, laggards with
    bear VCPs / bear flags, and a noisy middle. Exercises every part of the pipeline."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.today().normalize() - pd.offsets.BDay(1)
    idx = pd.bdate_range(end=end, periods=520)
    longs = "TWST TRMD SMTC UMC TH ADPT AMD SNDK ASX RIOT MU LITE INTC".split()
    shorts = "NKE LULU DG EL MRNA TGT BA CPB".split()
    rest = [f"DM{i:03d}" for i in range(380)]
    industries = ["Semiconductors", "Software", "Biotech", "Retail", "Apparel", "Oil & Gas",
                  "Airlines", "Food Products", "Banks", "Aerospace", "Medical Devices", "Shipping"]
    frames = {}
    for t in MARKET + longs + shorts + rest:
        lead, lag = t in longs, t in shorts
        drift = 0.0004 if t in MARKET else rng.uniform(0.0022, 0.0038) if (lead or lag) else rng.uniform(-0.0012, 0.0022)
        vol = 0.011 if t in MARKET else rng.uniform(0.018, 0.035)
        r = rng.normal(drift, vol, len(idx))
        c = 40 * np.exp(np.cumsum(r))
        k = (longs + shorts).index(t) if (lead or lag) else -1
        kk = k if lead else k - len(longs)
        shape = None
        if 0 <= kk < 4:
            shape = [(8, -0.22), (10, 0.26), (7, -0.12), (8, 0.12), (5, -0.06), (5, 0.045)]
        elif 4 <= kk < 7:
            shape = [(15, 0.45), (5, -0.06), (5, 0.02)]
        elif lead and t == "INTC":        # the weekly pivot press
            shape = [(50, 1.6), (20, -0.32), (12, 0.18), (10, -0.18), (12, 0.2), (10, -0.13), (5, 0.17)]
        if shape:
            total = sum(b for b, _ in shape)
            seg = [c[-total - 1]]
            for bars, move in shape:
                seg += list(np.geomspace(seg[-1], seg[-1] * (1 + move), bars + 1)[1:])
            c = np.r_[c[:-total], np.array(seg[1:]) * (1 + rng.normal(0, 0.004, total))]
        if lag:
            c = 1600 / c                   # laggards: the leader shape upside down
            c *= rng.uniform(30, 90) / c[-1]
        r = np.r_[0, np.diff(np.log(c))]
        quiet = shape is not None
        o = c * (1 + rng.normal(0, vol * (0.15 if quiet else 0.3), len(idx)))
        wick = vol * (0.25 if quiet else 0.5)
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, wick, len(idx))))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, wick, len(idx))))
        v = rng.lognormal(14.5 if (lead or lag) else 13.8, 0.4, len(idx)) * (1 + 8 * np.abs(r))
        if shape and 0 <= kk < 4:
            v[-30:] *= np.linspace(0.8, 0.4, 30)
        elif shape and t != "INTC":
            v[-25:-10] *= 2.5
            v[-10:] *= 0.5
        frames[t] = pd.DataFrame(dict(Open=o, High=h, Low=l, Close=c, Volume=v), index=idx)
    meta = {t: dict(sector="", industry=("Semiconductors" if t in longs[:8] else
                                         "Retail" if t in shorts else industries[i % len(industries)]),
                    mcap=round(float(rng.uniform(2e9, 9e11)), -8))
            for i, t in enumerate(longs + shorts + rest)}
    exch = {t: ("NASDAQ" if i % 2 else "NYSE") for i, t in enumerate(longs + shorts + rest)}
    return frames, meta, exch, set(longs + shorts)


def demo_options(t, price, closes, as_of):
    rng = np.random.default_rng(sum(map(ord, t)))
    iv = rng.uniform(0.3, 0.9)
    unusual = []
    if rng.random() < 0.5:
        k = "C" if rng.random() < 0.6 else "P"
        strike = round(price * (1.05 if k == "C" else 0.95))
        vol_ = int(rng.integers(2000, 15000))
        unusual.append(dict(k=k, strike=float(strike), exp="2026-10-16", dte=26, vol=vol_,
                            oi=int(vol_ / rng.uniform(3, 10)), prem=int(vol_ * rng.uniform(1, 6) * 100),
                            otm=round((strike / price - 1) * 100, 1)))
    tot = dict(oi=float(rng.integers(500, 90000)), vol=float(rng.integers(200, 40000)),
               cprem=float(rng.uniform(1e5, 5e6)), pprem=float(rng.uniform(1e5, 4e6)), unusual=unusual)
    return opt.summarize(tot, iv, rng.uniform(0.01, 0.3), bool(rng.random() < 0.7), opt.realized_vol(closes))


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="site/scan.json")
    ap.add_argument("--universe", help="scan only these tickers")
    ap.add_argument("--watchlist", default="scanner/watchlist.txt")
    ap.add_argument("--history", default="site/history", help="folder of dated scans for the scorecard")
    ap.add_argument("--backfill", type=int, default=0, help="rebuild this many past trading days of scans")
    ap.add_argument("--demo", action="store_true", help="synthetic data, no internet")
    ap.add_argument("--no-enrich", action="store_true", help="skip earnings and options lookups")
    ap.add_argument("--force", action="store_true", help="write even if the date was already scanned")
    a = ap.parse_args()

    out_path = Path(a.out)
    hist_dir = Path(a.history)
    prev = json.loads(out_path.read_text()) if out_path.exists() else {}
    watch = set(read_list(a.watchlist))

    if a.demo:
        import tempfile
        frames, meta, exch, _ = demo_world()
        watch = watch or {"AMD", "MU", "LITE"}
        prev = {}
        hist_dir = Path(tempfile.mkdtemp())      # never mix synthetic scans into real history
        a.backfill = a.backfill or 40
    else:
        from universe import download
        exch = {} if a.universe else full_market_universe()
        tickers = read_list(a.universe) if a.universe else list(exch)
        tickers = list(dict.fromkeys(tickers + sorted(watch) + MARKET))
        meta = fetch_meta(DATA / "meta.json")
        print(f"Universe: {len(tickers)} tickers ({len(watch)} from watchlist), metadata for {len(meta)}")
        frames = download(tickers)

    ctx = dict(meta=meta, exch=exch, watch=watch,
               prev={s: {r["t"] for r in prev.get(s, [])} for s in ("long", "short")},
               prev_asof=prev.get("as_of"))
    if a.backfill:
        backfill(frames, ctx, a.backfill, hist_dir)

    data, charts = build(frames, ctx)
    if prev.get("as_of") == data["as_of"] and not (a.force or a.demo):
        print(f"Already scanned {data['as_of']} (market holiday?). Nothing written.")
        return

    iv_path = DATA / "iv_history.json"
    iv_hist = opt.load_iv_history(iv_path)
    if a.demo:
        for side in ("long", "short"):
            add_options(data[side], frames, data["as_of"], {}, snap=demo_options)
    elif not a.no_enrich:
        for side in ("long", "short"):
            add_earnings(data[side], data["as_of"])
            add_options(data[side], frames, data["as_of"], iv_hist)
        opt.save_iv_history(iv_path, iv_hist, {r["t"] for s in ("long", "short") for r in data[s]})
    finish(data)
    data["demo"] = bool(a.demo)
    if not a.demo:   # the 60-bar mini charts are only needed for the offline sample
        for side in ("long", "short"):
            for r in data[side]:
                r.pop("ohlc", None)
                r.pop("ema", None)

    sc.write_history(hist_dir, data)
    data["scorecard"] = sc.evaluate(hist_dir, frames)
    if a.demo:   # keep the sample small and readable: named tickers only, two sample alerts
        for side in ("long", "short"):
            data[side] = [r for r in data[side] if not r["t"].startswith("DM")]
        data["passed"], data["passed_short"] = len(data["long"]), len(data["short"])
        charts = {k: v for k, v in charts.items() if not k.startswith("DM")}
        data["sample_alerts"] = {"date": data["as_of"], "fired": [
            dict(t=r["t"], side=r["side"], time=tm) for r, tm in
            ((data["long"][0], "10:05"), (data["short"][0], "11:40")) if r]}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, separators=(",", ":")))
    cdir = out_path.parent / "charts"
    cdir.mkdir(exist_ok=True)
    for old in cdir.glob("*.json"):
        old.unlink()
    for key, ch in charts.items():
        (cdir / f"{key}.json").write_text(json.dumps(ch, separators=(",", ":")))
    print(f"{data['as_of']}: {data['passed']} long, {data['passed_short']} short of {data['liquid']} liquid "
          f"| regime {data['regime']['level']} | scorecard {data['scorecard']['scans']} scans -> {out_path}")


if __name__ == "__main__":
    main()
