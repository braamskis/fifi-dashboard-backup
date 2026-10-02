"""Massive downloader against a stubbed API: python scanner/test_massive.py"""
import datetime as dt

import massive_data
import universe

ok = True
calls = {"n": 0}


def fake_grouped(date, key):
    calls["n"] += 1
    d = dt.date.fromisoformat(date)
    if d.weekday() >= 5 or (d.month, d.day) == (7, 4):      # weekend / holiday: empty
        return []
    i = (dt.date.today() - d).days
    return [{"T": "AAA", "o": 100 + i, "h": 101 + i, "l": 99 + i, "c": 100.5 + i, "v": 1e6},
            {"T": "BBB", "o": 50, "h": 51, "l": 49, "c": 50.5, "v": 2e6},
            {"T": "ZZZ", "o": 5, "h": 6, "l": 4, "c": 5.5, "v": 100},      # not in our universe
            {"T": "NOPRICE", "o": None, "h": None, "l": None, "c": None, "v": 0}]


massive_data.grouped_day = fake_grouped
frames = massive_data.download(["AAA", "BBB"], days=30, key="test", progress_every=1000)

checks = [
    ("only requested tickers", sorted(frames) == ["AAA", "BBB"]),
    ("30 trading days each", all(len(df) == 30 for df in frames.values())),
    ("weekends skipped", all(i.weekday() < 5 for i in frames["AAA"].index)),
    ("oldest first", frames["AAA"].index.is_monotonic_increasing),
    ("columns", list(frames["AAA"].columns) == ["Open", "High", "Low", "Close", "Volume"]),
    ("prices are floats", frames["AAA"]["Close"].dtype.kind == "f"),
    ("no more calls than calendar days", calls["n"] <= 45),
]
for name, good in checks:
    print(("PASS" if good else "FAIL") + "  " + name)
    ok &= good

# fallback: Massive raises -> Yahoo path is used
massive_data.download = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("api down"))
universe.download_yahoo = lambda tickers, chunk=200: {"FELLBACK": "yahoo"}
import os
os.environ["MASSIVE_API_KEY"] = "test"
got = universe.download(["AAA"])
print(("PASS" if got == {"FELLBACK": "yahoo"} else "FAIL") + "  falls back to Yahoo on API failure")
ok &= got == {"FELLBACK": "yahoo"}

raise SystemExit(0 if ok else 1)
