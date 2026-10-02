"""
FiFi's Dashboard core: indicators, pattern detectors, per-stock metrics, key levels
and the TQE grade. Side-agnostic: the short side runs the same code on an
inverted chart (see invert()).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_BARS = 260
INVERT_K = 10_000.0


def invert(df: pd.DataFrame) -> pd.DataFrame:
    """Upside-down chart (price -> K / price). Downtrends become uptrends, bear flags
    become bull flags, breakdowns become breakouts. Percent ranges are preserved
    (high/low ratio is identical), so ADR and tightness carry over."""
    return pd.DataFrame({
        "Open": INVERT_K / df["Open"], "High": INVERT_K / df["Low"],
        "Low": INVERT_K / df["High"], "Close": INVERT_K / df["Close"],
        "Volume": df["Volume"],
    }, index=df.index)


# ------------------------------------------------------------------ indicators
def _sma(a, n):
    return pd.Series(a).rolling(n).mean().to_numpy()


def _ema(a, n):
    return pd.Series(a).ewm(span=n, adjust=False).mean().to_numpy()


# ------------------------------------------------------------------ patterns
def swings(h, l, k: int = 3) -> list[tuple[int, float, str]]:
    """Alternating swing highs (H) and lows (L), each confirmed by k bars on both sides."""
    pts = []
    for i in range(k, len(h) - k):
        if h[i] == h[i - k:i + k + 1].max():
            pts.append((i, float(h[i]), "H"))
        if l[i] == l[i - k:i + k + 1].min():
            pts.append((i, float(l[i]), "L"))
    out: list[tuple[int, float, str]] = []
    for p in pts:                      # two highs in a row: keep the higher, etc.
        if out and out[-1][2] == p[2]:
            if (p[2] == "H" and p[1] >= out[-1][1]) or (p[2] == "L" and p[1] <= out[-1][1]):
                out[-1] = p
        else:
            out.append(p)
    return out


DAILY = dict(lookback=90, min_base=12, skip=3, k=3, noise=0.02, first_max=0.35, last_cap=0.12,
             last_floor=0.10, near=(0.94, 1.03), vol=(10, 50), per_week=5,
             f_win=30, f_len=(4, 25), f_pre=40, f_run=0.30, f_tight_n=5, htf=True)
WEEKLY = dict(lookback=52, min_base=6, skip=1, k=2, noise=0.03, first_max=0.45, last_cap=0.20,
              last_floor=0.12, near=(0.92, 1.05), vol=(4, 20), per_week=1,
              f_win=13, f_len=(2, 10), f_pre=16, f_run=0.40, f_tight_n=3, htf=False)


def find_vcp(h, l, c, v, adr: float, p: dict = DAILY) -> dict | None:
    """Minervini volatility contraction pattern.

    Base = from the highest high of the last `lookback` bars. Each pullback
    (swing high to the next swing low) is a contraction. Needs 2+ contractions
    in a row that each get shallower, the first no deeper than 35%, the last
    tight (10% or 2 ADRs, max 12%), volume drying up, and price within 6%
    below or 3% above the pivot (high of the last contraction)."""
    lookback = p["lookback"]
    n = len(c)
    if n < lookback + 5:
        return None
    s = n - lookback
    H, L = h[s:], l[s:]
    top = int(np.argmax(H[:-p["skip"]]))
    if top > lookback - p["min_base"]:  # the base needs some width
        return None
    noise = max(p["noise"], 0.75 * adr / 100)
    last_h = (top, float(H[top]))
    cons = []                          # (high, low, high_idx, low_idx)
    for i, price, kind in swings(H, L, p["k"]):
        if i <= top:
            continue
        if kind == "H":
            last_h = (i, price)
        elif (last_h[1] - price) / last_h[1] >= noise:
            if cons and cons[-1][2] == last_h[0]:          # same high, deeper low
                cons[-1] = (last_h[1], min(price, cons[-1][1]), last_h[0], i)
            else:
                cons.append((last_h[1], price, last_h[0], i))
    # the pullback still in progress on the right side of the base
    if last_h[0] < len(H) - 1 and (not cons or cons[-1][2] != last_h[0]):
        lo = float(L[last_h[0] + 1:].min())
        if (last_h[1] - lo) / last_h[1] >= noise * 0.5:
            cons.append((last_h[1], lo, last_h[0], last_h[0] + 1 + int(np.argmin(L[last_h[0] + 1:]))))
    if len(cons) < 2:
        return None
    depths = [(hi - lo) / hi for hi, lo, _, _ in cons]
    chain = [depths[-1]]               # shallower-each-time run, counted from the right
    for d in reversed(depths[:-1]):
        if d >= chain[0] * 1.10:
            chain.insert(0, d)
        else:
            break
    last = chain[-1]
    pivot, low = cons[-1][0], cons[-1][1]
    ok = (
        len(chain) >= 2
        and chain[0] <= p["first_max"]
        and chain[0] >= 2 * last
        and last <= min(p["last_cap"], max(p["last_floor"], 2 * adr / 100))
        and pivot * p["near"][0] <= c[-1] <= pivot * p["near"][1]
        and c[-1] >= low
        and np.mean(v[-p["vol"][0]:]) < 0.9 * np.mean(v[-p["vol"][1]:])
    )
    if not ok:
        return None
    points = [(s + hi_i, hi, s + lo_i, lo) for hi, lo, hi_i, lo_i in cons[-len(chain):]]
    return dict(t=len(chain), depths=[round(d * 100) for d in chain],
                pivot=float(pivot), stop=float(low), weeks=round((lookback - top) / p["per_week"]),
                points=points)


def find_flag(h, l, c, v, adr: float, p: dict = DAILY) -> dict | None:
    """Qullamaggie-style tight flag, and O'Neil's high tight flag.

    Flag top = highest high of the last 30 bars, 4-25 bars ago. Impulse = low of
    the 40 bars before the top to the top. Flag depth = top to lowest low since."""
    n = len(c)
    win = p["f_win"]
    top = n - win + int(np.argmax(h[-win:]))
    flag_len = n - 1 - top
    if not p["f_len"][0] <= flag_len <= p["f_len"][1]:
        return None
    start = max(0, top - p["f_pre"])
    lo_i = start + int(np.argmin(l[start:top + 1]))
    run = h[top] / l[lo_i] - 1
    run_days = top - lo_i
    flag_low = float(l[top + 1:].min())
    depth = (h[top] - flag_low) / h[top]
    tn = p["f_tight_n"]
    range5 = (h[-tn:].max() - l[-tn:].min()) / c[-1]
    lighter = np.mean(v[top + 1:]) < np.mean(v[lo_i:top + 1])
    base = run_days >= (3 if p is DAILY else 2) and depth <= 0.25 and depth <= run * 0.5 and lighter and c[-1] >= h[top] * 0.85
    if not base:
        return None
    kind = None
    if p["htf"] and run >= 0.90 and run_days <= 40:
        kind = "HTF"
    elif run >= p["f_run"] and range5 <= 2.5 * adr / 100:
        kind = "FLAG"
    if not kind:
        return None
    return dict(kind=kind, run=round(run * 100), run_days=int(run_days), days=int(flag_len),
                depth=round(depth * 100), pivot=float(h[top]),
                stop=float(l[-tn:].min()), lo_i=int(lo_i), top_i=int(top), lo=float(l[lo_i]))


def three_weeks_tight(df: pd.DataFrame) -> bool:
    wk = df["Close"].resample("W-FRI").last().dropna()
    if len(wk) < 4:
        return False
    w = wk.iloc[-3:].to_numpy()
    return bool(w.max() / w.min() - 1 <= 0.015 and wk.iloc[-1] >= wk.iloc[-8:].max() * 0.9)


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Weekly bars (week ending Friday). The current week may be partial; `days`
    says how many sessions it has so far."""
    w = df.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min",
                                  "Close": "last", "Volume": "sum"}).dropna()
    w["days"] = df["Close"].resample("W-FRI").count().reindex(w.index)
    return w


def weekly_setup(df: pd.DataFrame) -> dict | None:
    """Weekly base breakouts, like a stock building 5-50 weeks after a big run and then
    taking out the right-side pivot.

    pivot  highest weekly high of the prior 8 weeks (the right side of the base)
    WBO    this week closes through the pivot, closes in the upper half of its range,
           and volume is running at or above the 10-week average (partial weeks are paced)
    WPV    this week is a strong up week pressing the pivot (high within 1% of it or
           above) but has not closed through yet: the INTC-style setup
    both   need a real base (52-week high 5+ weeks ago, no deeper than 45%), price above
           the 10-week MA, and a rising 40-week MA
    WVCP / WFLAG  the daily detectors run on weekly bars with weekly settings"""
    w = to_weekly(df)
    if len(w) < 60:
        return None
    o, h, l, c, v = (w[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    wadr = float(np.mean(h[-10:] / l[-10:] - 1) * 100)
    m10, m20, m40 = _sma(c, 10), _sma(c, 20), _sma(c, 40)
    days = float(w["days"].iloc[-1] or 5)
    pace = v[-1] * 5 / max(days, 1)
    vavg = float(np.mean(v[-11:-1]))
    pivot = float(h[-9:-1].max())
    top_i = len(h) - 53 + int(np.argmax(h[-53:-1]))
    base_weeks = len(h) - 1 - top_i
    depth = (h[top_i] - l[top_i:].min()) / h[top_i]
    rng = h[-1] - l[-1]
    upper = rng > 0 and (c[-1] - l[-1]) / rng >= 0.5
    trend = c[-1] > m10[-1] and m40[-1] > m40[-5] and c[-1] > m40[-1]
    based = 5 <= base_weeks <= 52 and depth <= 0.45
    wbo = based and trend and c[-1] > pivot and upper and pace >= vavg
    wpv = (based and trend and not wbo and h[-1] >= pivot * 0.99 and c[-1] >= pivot * 0.95
           and c[-1] > o[-1] and upper)
    wvcp = find_vcp(h, l, c, v, wadr, WEEKLY)
    wflag = find_flag(h, l, c, v, wadr, WEEKLY)
    if not (wbo or wpv or wvcp or wflag):
        return None
    dates = [str(pd.Timestamp(d).date()) for d in w.index]
    return dict(
        WBO=bool(wbo), WPV=bool(wpv), WVCP=wvcp, WFLAG=wflag,
        pivot=float(wvcp["pivot"] if wvcp else pivot),
        stop=float(wvcp["stop"] if wvcp else min(l[-1], l[-2])),
        base_weeks=int(base_weeks), depth=round(depth * 100), pace=round(pace / vavg, 2) if vavg else None,
        stack=bool(c[-1] > m10[-1] > m20[-1] > m40[-1]),
        top_date=dates[top_i], dates=dates,
    )


def rs_flags(c: np.ndarray, bench: np.ndarray | None, near_high: bool) -> dict:
    """RS line = price / benchmark (SPY). RSNH: RS line at a 52-week high today.
    RSBP: RS line at a new high while price is not (the O'Neil / Minervini early tell)."""
    if bench is None or len(bench) != len(c):
        return dict(RSNH=False, RSBP=False)
    rs = c / bench
    nh = bool(rs[-1] >= rs[-252:].max() * 0.999)
    return dict(RSNH=nh, RSBP=bool(nh and not near_high))


def metrics(t: str, df: pd.DataFrame, bench: pd.Series | None = None) -> dict | None:
    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
    if len(df) < MIN_BARS:
        return None
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    last = c[-1]
    if not np.isfinite(last) or last <= 0:
        return None

    s50, s150, s200 = _sma(c, 50), _sma(c, 150), _sma(c, 200)
    e8, e21, e50 = _ema(c, 8), _ema(c, 21), _ema(c, 50)
    hi52, lo52 = h[-252:].max(), l[-252:].min()
    avgv50 = float(np.mean(v[-50:]))
    dvol50 = float(np.mean(c[-50:] * v[-50:]))
    adr = float(np.mean(h[-20:] / l[-20:] - 1) * 100)

    n = len(c)

    def ret(k):
        return float(c[-1] / c[-1 - k] - 1) if n > k and c[-1 - k] > 0 else float("nan")

    # Minervini trend template, rules 1-7 (rule 8 = RS, applied after ranking)
    tt = all([
        last > s150[-1] and last > s200[-1],
        s150[-1] > s200[-1],
        s200[-1] > s200[-22],
        s50[-1] > s150[-1] and s50[-1] > s200[-1],
        last > s50[-1],
        last >= 1.30 * lo52,
        last >= 0.75 * hi52,
    ])

    # Weinstein stage from the 30-week (150-day) average
    rising = s150[-1] > s150[-21]
    if last > s150[-1] and rising:
        below = np.where(c[-252:] < s150[-252:])[0]
        since = 251 - below[-1] if len(below) else 252
        stage = "2A" if since <= 65 else "2B"
    elif last > s150[-1]:
        stage = "1"
    elif rising:
        stage = "3"
    else:
        stage = "4"

    # Darvas box breakout in the last 5 sessions, still holding above the box
    darvas = False
    max_depth = max(0.15, 3 * adr / 100)
    for k in range(1, 6):
        j = len(c) - k
        top, bot = h[j - 20:j].max(), l[j - 20:j].min()
        if top / bot - 1 <= max_depth and c[j] > top and c[j - 1] <= top and last >= top:
            darvas = True
            break

    chg1 = ret(1)
    pivot = float(h[-20:].max())
    stop, stop_note = float(l[-3:].min()), "3-day"

    vcp = find_vcp(h, l, c, v, adr)
    flag = find_flag(h, l, c, v, adr)
    if vcp:
        pivot, stop, stop_note = vcp["pivot"], vcp["stop"], "last contraction"
    elif flag:
        pivot, stop, stop_note = flag["pivot"], flag["stop"], "5-day flag"
    b = bench.reindex(df.index).ffill().to_numpy(float) if bench is not None else None
    rsf = rs_flags(c, b, last >= 0.95 * hi52)
    wk = weekly_setup(df)
    if wk and not vcp and not flag:
        pivot, stop = wk["pivot"], wk["stop"]
        stop_note = "weekly contraction" if wk["WVCP"] else "2-week"
    rng = h - l
    down10 = [v[i] for i in range(n - 11, n - 1) if c[i] < c[i - 1]]

    return dict(
        t=t, price=last, chg1d=chg1, chg5d=ret(5),
        r21=ret(21), r63=ret(63), r126=ret(126), r189=ret(189), r252=ret(252),
        adr=adr, avgv50=avgv50, dvol50=dvol50, vol=float(v[-1]),
        tt=bool(tt), stage=stage,
        above50=bool(last > s50[-1]), above200=bool(last > s200[-1]),
        newhigh=bool(h[-1] >= h[-253:-1].max()), newlow=bool(l[-1] <= l[-253:-1].min()),
        flags=dict(
            SB4=bool(chg1 >= 0.04 and v[-1] > v[-2] and v[-1] >= 100_000),
            SBW=bool(ret(5) >= 0.20),
            **{"9M": bool(v[-1] >= 9_000_000)},
            HV=bool(v[-1] >= v[-253:-1].max()),
            LQ=bool(dvol50 >= 100e6 and ret(126) >= 0.30),
            **{"52W": bool(h[-1] >= h[-253:-1].max())},
            DB=bool(darvas),
            VCP=bool(vcp),
            FLAG=bool(flag and flag["kind"] == "FLAG"),
            HTF=bool(flag and flag["kind"] == "HTF"),
            **{"3WT": three_weeks_tight(df)},
            NR7=bool(rng[-1] <= rng[-7:].min()),
            ID=bool(h[-1] <= h[-2] and l[-1] >= l[-2]),
            PP=bool(c[-1] > c[-2] and down10 and v[-1] > max(down10) and last > s50[-1]),
            EXT=bool((last / s50[-1] - 1) / max(adr / 100, 1e-4) >= 7),
            EMA=bool(last > e8[-1] > e21[-1] > e50[-1]),
            RSNH=rsf["RSNH"], RSBP=rsf["RSBP"],
            WBO=bool(wk and wk["WBO"]), WPV=bool(wk and wk["WPV"]),
            WVCP=bool(wk and wk["WVCP"]), WFLAG=bool(wk and wk["WFLAG"]),
            near20=bool(last >= 0.90 * pivot and last > _sma(c, 20)[-1]),
            onbase=bool(last >= 0.85 * hi52 and s50[-1] > s200[-1] and last > s50[-1]
                        and avgv50 >= 300_000),
        ),
        # inputs for the TQE grade
        pivot=pivot, stop=stop, stop_note=stop_note, vcp=vcp, flag=flag, weekly=wk,
        range10=float((h[-10:].max() - l[-10:].min()) / last),
        vdry=float(np.mean(v[-5:]) / avgv50) if avgv50 else 1.0,
        ext21=float((last / e21[-1] - 1) / max(adr / 100, 1e-4)),
        stack=2 if last > e8[-1] > e21[-1] > e50[-1] else (1 if e8[-1] > e21[-1] > e50[-1] else 0),
        ema21=float(e21[-1]), sma50=float(s50[-1]), above21=bool(last > e21[-1]),
        e21_gt_50=bool(e21[-1] > s50[-1]),
        date=str(pd.Timestamp(df.index[-1]).date()),
    )


# ------------------------------------------------------------------ TQE grade
def _lin(x, good, bad):
    """1.0 at `good`, 0.0 at `bad`, linear in between (works either direction)."""
    if not np.isfinite(x):
        return 0.0
    f = (x - bad) / (good - bad)
    return float(min(1.0, max(0.0, f)))


def grade(m: dict, bonus: float = 0) -> tuple[int, str]:
    """0-100 setup score and letter. `bonus` = group-strength adjustment (+/-5)."""
    dist = (m["pivot"] - m["price"]) / m["price"]            # % below 20-day high
    tight = m["range10"] * 100 / max(m["adr"], 0.1)            # 10-day range in ADR units
    ext = m["ext21"]
    score = (
        25 * m["rs"] / 99                                      # leadership
        + 20 * _lin(dist, 0.0, 0.10)                           # close to the pivot
        + 20 * _lin(tight, 2.0, 6.0)                           # tight base
        + 10 * _lin(m["vdry"], 0.6, 1.3)                       # volume drying up
        + 15 * (_lin(ext, 1.5, 5.0) if ext >= 0 else 0.33)     # not extended from 21 EMA
        + 10 * (1.0, 0.6, 0.0)[2 - m["stack"]]                 # 8/21/50 stack
    )
    s = int(round(min(100, max(0, score + bonus))))
    for cut, g in ((85, "A+"), (75, "A"), (65, "B"), (55, "C"), (45, "D")):
        if s >= cut:
            return s, g
    return s, "F"

# ------------------------------------------------------------------ key levels
def key_levels(df: pd.DataFrame) -> dict:
    """Weekly open, prior-month high/low and the nearest unfilled daily gaps (real chart)."""
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    idx = df.index
    cur = pd.Timestamp(idx[-1])
    in_month = (idx.year == cur.year) & (idx.month == cur.month)
    before = df[idx < df[in_month].index[0]]
    pm = before[(before.index.year == before.index[-1].year) & (before.index.month == before.index[-1].month)]
    week = df[idx >= (cur - pd.Timedelta(days=cur.weekday())).normalize()]
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    last = float(df["Close"].iloc[-1])
    gaps = []
    n = len(df)
    for i in range(max(1, n - 60), n):
        if l[i] > h[i - 1] and (i == n - 1 or l[i + 1:].min() > h[i - 1]):
            gaps.append(dict(dir="up", lo=round(h[i - 1], 2), hi=round(l[i], 2), date=str(idx[i].date())))
        if h[i] < l[i - 1] and (i == n - 1 or h[i + 1:].max() < l[i - 1]):
            gaps.append(dict(dir="down", lo=round(h[i], 2), hi=round(l[i - 1], 2), date=str(idx[i].date())))
    gaps.sort(key=lambda g: abs((g["lo"] + g["hi"]) / 2 - last))
    return dict(
        wo=round(float(week["Open"].iloc[0]), 2),
        pm_h=round(float(pm["High"].max()), 2), pm_l=round(float(pm["Low"].min()), 2),
        gaps=gaps[:3],
    )
