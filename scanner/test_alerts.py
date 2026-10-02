"""Alert trigger logic: python scanner/test_alerts.py"""
import datetime as dt

import pandas as pd

import alerts

now = dt.datetime(2026, 9, 21, 11, 0, tzinfo=alerts.ET)
rows = [dict(t="AAA", side="long", grade="A", badges=["VCP"], score=80, avgv=1e6,
             levels=dict(pivot=100.0, stop=95.0)),
        dict(t="BBB", side="short", grade="A", badges=["FLAG"], score=78, avgv=1e6,
             levels=dict(pivot=50.0, stop=53.0)),
        dict(t="CCC", side="long", grade="A+", badges=[], score=90, avgv=1e6,
             levels=dict(pivot=20.0, stop=19.0))]
bars = lambda hi, lo, last, vol: pd.DataFrame(dict(High=[hi], Low=[lo], Close=[last], Volume=[vol]))
intraday = {"AAA": bars(101, 98, 100.4, 6e5),   # through the pivot and holding
            "BBB": bars(51, 49.5, 49.8, 3e5),   # through the trigger
            "CCC": bars(20.3, 19.2, 19.5, 2e5)}  # tagged the pivot but faded: no alert
got = alerts.check(rows, intraday, set(), now)
names = sorted(a["t"] for a in got)
ok = names == ["AAA", "BBB"]
print(("PASS" if ok else "FAIL") + f"  triggers {names}, AAA pace {got[0]['pace']}x")
again = alerts.check(rows, intraday, {"AAA:long", "BBB:short"}, now)
ok &= not again
print(("PASS" if not again else "FAIL") + "  no repeat alerts")
raise SystemExit(0 if ok else 1)
