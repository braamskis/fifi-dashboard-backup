"""RRG maths on constructed series: python scanner/test_rrg.py"""
import numpy as np
import pandas as pd

import rrg

idx = pd.bdate_range(end="2026-09-18", periods=800)
n = len(idx)
bench = pd.Series(100 * np.exp(np.cumsum(np.full(n, 0.0003))), index=idx)

# steady outperformer -> should end Leading (x>100, y>=100)
lead = pd.Series(100 * np.exp(np.cumsum(np.full(n, 0.0012))), index=idx)
# steady underperformer -> Lagging
lag = pd.Series(100 * np.exp(np.cumsum(np.full(n, -0.0006))), index=idx)
# was weak, turned up hard in the last 6 months -> Improving or Leading, not Lagging
turn = pd.Series(100 * np.exp(np.cumsum(np.r_[np.full(n - 130, -0.0008), np.full(130, 0.0025)])), index=idx)

ok = True


def check(name, got, want):
    global ok
    good = got in want if isinstance(want, (list, tuple)) else got == want
    print(("PASS" if good else "FAIL") + f"  {name}: {got}")
    ok &= good


for name, s, want in [("outperformer", lead, ["Leading", "Weakening"]),
                      ("underperformer", lag, ["Lagging", "Improving"]),
                      ("recent turn up", turn, ["Improving", "Leading"])]:
    pts = rrg.rrg_points(s, bench)
    check(name + " has a full tail", len(pts) == rrg.TAIL, True)
    check(name + " quadrant", rrg.quadrant(pts[-1]["x"], pts[-1]["y"]), want)

pts = rrg.rrg_points(lead, bench)
check("points are dated weekly", (pd.Timestamp(pts[-1]["d"]) - pd.Timestamp(pts[-2]["d"])).days, 7)
check("centred near 100", 85 < pts[-1]["x"] < 115 and 85 < pts[-1]["y"] < 115, True)
check("short history returns nothing", len(rrg.rrg_points(lead.tail(100), bench.tail(100))) == 0, True)

data = rrg.build({"SPY": bench, "XLK": lead, "XLE": lag})
check("build keeps known sectors", sorted(i["t"] for i in data["items"]), [["XLE", "XLK"]])
check("sorted by RS-Ratio", data["items"][0]["t"], "XLK")

raise SystemExit(0 if ok else 1)
