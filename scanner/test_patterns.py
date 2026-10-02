"""Sanity tests for the pattern detectors: python scanner/test_patterns.py"""
import numpy as np
import pandas as pd

import core as scan


def path(legs, start=50.0, seed=1, wiggle=0.004):
    """Piecewise-linear closes through (bars, target) legs, with a little noise."""
    rng = np.random.default_rng(seed)
    c = [start]
    for bars, target in legs:
        c += list(np.linspace(c[-1], target, bars + 1)[1:])
    c = np.array(c) * (1 + rng.normal(0, wiggle, len(c)))
    h, l = c * 1.01, c * 0.99
    return h, l, c


def adr(h, l):
    return float(np.mean(h[-20:] / l[-20:] - 1) * 100)


def check(name, got, want):
    print(f"{'PASS' if bool(got) == want else 'FAIL'}  {name}: {got}")
    return bool(got) == want


ok = True

# VCP: 22% -> 11% -> 5% pullbacks, volume drying up, sitting just under the pivot
h, l, c = path([(300, 100), (8, 78), (10, 97), (7, 86), (8, 95), (5, 90), (5, 94)])
v = np.r_[np.full(len(c) - 30, 2e6), np.linspace(1.6e6, 0.8e6, 30)]
ok &= check("VCP detected", scan.find_vcp(h, l, c, v, adr(h, l)), True)

# Same base but the pullbacks get DEEPER: not a VCP
h, l, c = path([(300, 100), (8, 94), (10, 99), (7, 88), (8, 97), (5, 80), (8, 93)])
ok &= check("Widening base rejected", scan.find_vcp(h, l, c, v, adr(h, l)), False)

# Tight flag: +42% in 15 days, then 10 quiet days
h, l, c = path([(300, 60), (15, 85), (5, 81), (5, 82)])
v = np.r_[np.full(len(c) - 25, 2e6), np.full(15, 5e6), np.full(10, 1.5e6)]
f = scan.find_flag(h, l, c, v, adr(h, l))
ok &= check("Flag detected", f and f["kind"] == "FLAG" and f, True)

# High tight flag: +100% in 30 days, then a 15% pullback
h, l, c = path([(300, 40), (30, 80), (6, 68), (8, 74)])
v = np.r_[np.full(len(c) - 44, 2e6), np.full(30, 6e6), np.full(14, 2e6)]
f = scan.find_flag(h, l, c, v, adr(h, l))
ok &= check("High tight flag detected", f and f["kind"] == "HTF" and f, True)

# Random walks: should rarely trigger anything
hits = 0
for seed in range(200):
    rng = np.random.default_rng(seed)
    c = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, 400)))
    h, l = c * (1 + np.abs(rng.normal(0, 0.01, 400))), c * (1 - np.abs(rng.normal(0, 0.01, 400)))
    v = rng.lognormal(14, 0.4, 400)
    hits += bool(scan.find_vcp(h, l, c, v, adr(h, l))) + bool(scan.find_flag(h, l, c, v, adr(h, l)))
print(f"{'PASS' if hits <= 20 else 'FAIL'}  random walks: {hits} hits in 400 checks")
ok &= hits <= 20

# 3 weeks tight
idx = pd.bdate_range(end="2026-09-18", periods=60)
closes = np.r_[np.linspace(40, 60, 45), [60.2, 60.4, 60.1, 60.3, 60.0, 60.3, 60.2, 60.5, 60.4, 60.3, 60.4, 60.2, 60.6, 60.4, 60.5]]
ok &= check("3 weeks tight", scan.three_weeks_tight(pd.DataFrame({"Close": closes}, index=idx)), True)

# Weekly: INTC-style. Big run, ~10-12 week base under a right-side pivot, then a strong week.
def daily_df(legs, start=20.0, seed=3, vol_last=None):
    h, l, c = path(legs, start=start, seed=seed, wiggle=0.006)
    idx = pd.bdate_range(end="2026-09-18", periods=len(c))
    o = np.r_[c[0], c[:-1]]
    v = np.full(len(c), 3e7)
    if vol_last:
        v[-5:] = vol_last
    return pd.DataFrame(dict(Open=o, High=np.maximum(h, o), Low=np.minimum(l, o), Close=c, Volume=v), index=idx)

base = [(300, 40), (50, 140), (20, 95), (12, 112), (10, 92), (12, 110), (10, 96)]
press = scan.weekly_setup(daily_df(base + [(5, 113)]))
ok &= check("Weekly pivot press (WPV)", press and press["WPV"] and press, True)
brk = scan.weekly_setup(daily_df(base + [(5, 118)], vol_last=6e7))
ok &= check("Weekly breakout (WBO)", brk and brk["WBO"], True)
dn = scan.weekly_setup(daily_df(base + [(5, 90)]))
ok &= check("Weak week rejected", dn and (dn["WBO"] or dn["WPV"]), False)

# RS line: stock flat under its high while the benchmark falls -> RS new high before price
c = np.r_[np.linspace(50, 100, 200), np.linspace(100, 90, 60)]
b = np.r_[np.linspace(400, 450, 200), np.linspace(450, 360, 60)]
f = scan.rs_flags(c, b, near_high=c[-1] >= 0.95 * c.max())
ok &= check("RS new high before price", f["RSBP"], True)

raise SystemExit(0 if ok else 1)
