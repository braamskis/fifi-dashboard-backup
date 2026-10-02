#!/usr/bin/env python3
"""
Prime ideas: the short list worth real size.

Runs after the scan and the rotation step, reads site/scan.json and site/rrg.json,
and adds three things:

  sector alignment  each stock's sector mapped to its RRG quadrant, so longs in
                    Leading / Improving sectors and shorts in Lagging / Weakening
                    ones are marked (SEC badge)
  themes            industries with 3+ setups on the same side the same night,
                    which is usually a group move starting (THEME badge)
  prime             setups that clear every low-risk test below, each with a plan:
                    entry, stop, risk, and 2R / 3R targets

Prime tests (a long; shorts are the mirror):
  - grade A or A+
  - a real pattern, not just a trend-template pass
  - stop within 6% of price, so a full stop-out is a small loss
  - price within 4% of the pivot, so it is actionable now, not a watch item
  - not extended (no EXT), no earnings inside 7 days (no ER+)
  - options are tradeable (not THIN)
  - sector in Leading or Improving; industry group not in the bottom half

  python scanner/prime.py --scan site/scan.json --rrg site/rrg.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SETUPS = {"VCP", "FLAG", "HTF", "WBO", "WPV", "WVCP", "WFLAG", "3WT"}
RVOL_N = 50              # relative volume is measured against this many days
MAX_RISK = 0.06          # stop no further than 6% away
MAX_TO_TRIGGER = 0.04    # price within 4% of the pivot / trigger
THEME_MIN = 3            # setups in one industry before it counts as a theme

# Nasdaq's sector names -> the sector ETF that represents them on the RRG
SECTOR_ETF = {
    "Technology": "XLK", "Computer and Technology": "XLK", "Semiconductors": "XLK",
    "Finance": "XLF", "Financials": "XLF", "Energy": "XLE", "Oils/Energy": "XLE",
    "Health Care": "XLV", "Medical": "XLV", "Industrials": "XLI", "Capital Goods": "XLI",
    "Transportation": "XLI", "Aerospace": "XLI", "Consumer Discretionary": "XLY",
    "Consumer Services": "XLY", "Retail/Wholesale": "XLY", "Auto/Tires/Trucks": "XLY",
    "Consumer Staples": "XLP", "Consumer Durables": "XLY", "Consumer Non-Durables": "XLP",
    "Utilities": "XLU", "Public Utilities": "XLU", "Basic Materials": "XLB",
    "Basic Industries": "XLB", "Industrial Products": "XLB", "Real Estate": "XLRE",
    "Telecommunications": "XLC", "Communication Services": "XLC", "Media": "XLC",
}
GOOD_LONG = {"Leading", "Improving"}
GOOD_SHORT = {"Lagging", "Weakening"}


def sector_quadrants(rrg: dict | None) -> dict[str, str]:
    return {i["t"]: i["quadrant"] for i in (rrg or {}).get("items", [])}


def tape(row: dict, charts: Path) -> None:
    """Relative volume and distance from the 8 / 21 / 50 EMAs, read from the row's chart file."""
    row["rvol"] = row["ema_dist"] = None
    f = charts / f"{row['t']}-{row['side']}.json"
    if not f.exists():
        return
    try:
        ch = json.loads(f.read_text())
        bars, ema = ch["bars"], ch.get("ema") or {}
        vols = [b[5] for b in bars[-RVOL_N - 1:-1] if b[5]]
        today = bars[-1][5]
        if vols and today:
            row["rvol"] = round(today / (sum(vols) / len(vols)), 2)
        close = bars[-1][4]
        row["ema_dist"] = [round((close / ema[n][-1] - 1) * 100, 1)
                           for n in ("8", "21", "50") if ema.get(n) and ema[n][-1]]
    except Exception:
        pass


def confluence(row: dict, theme: bool) -> float:
    """One number for how much is lining up, on a 0-20 scale.

    Setup quality carries the most weight, then the tape (relative volume), then the
    context: sector rotation, group strength, a group move, and how tight the stop is."""
    long = row["side"] == "long"
    grp = (row.get("grp") or {}).get("rank")
    quad = row.get("sector_quadrant")
    risk = (row.get("plan") or {}).get("risk") or 1
    pts = 6 * min(row["score"], 100) / 100
    pts += 3 * min((row.get("rvol") or 1) / 2.5, 1)
    pts += 3 if quad in (GOOD_LONG if long else GOOD_SHORT) else (1.5 if quad else 0)
    if grp is not None:
        pts += 2 * ((grp / 99) if long else (1 - grp / 99))
    pts += 2 if theme else 0
    pts += 2 * max(0.0, 1 - risk / MAX_RISK)
    pts += 2 * len(SETUPS & set(row["badges"])) / 3
    return round(min(pts, 20), 1)


def bucket(row: dict) -> str:
    """Their layout: leading sectors, rotation candidates, then earnings as its own risk box."""
    b, quad = set(row["badges"]), row.get("sector_quadrant")
    if "ER+" in b or "ER-1" in b:
        return "earnings"
    if row["side"] == "long":
        return "leading" if quad == "Leading" else "improving" if quad == "Improving" else "other"
    return "lagging" if quad == "Lagging" else "weakening" if quad == "Weakening" else "other"


def plan(row: dict) -> dict:
    """Entry, stop and R-multiple targets from the row's own levels."""
    entry, stop = row["levels"]["pivot"], row["levels"]["stop"]
    r = abs(entry - stop)
    up = row["side"] == "long"
    return dict(entry=round(entry, 2), stop=round(stop, 2), r=round(r, 2),
                risk=round(r / entry, 4) if entry else None,
                t2=round(entry + 2 * r, 2) if up else round(entry - 2 * r, 2),
                t3=round(entry + 3 * r, 2) if up else round(entry - 3 * r, 2),
                to_trigger=round(entry / row["price"] - 1, 4))


def checklist(row: dict, quad: str | None) -> list[dict]:
    """Every low-risk test, with the answer, so the dashboard can show the reasoning."""
    long = row["side"] == "long"
    p, b = row["plan"], set(row["badges"])
    grp = (row.get("grp") or {}).get("rank")
    to_trigger = p["to_trigger"] if long else -p["to_trigger"]
    return [
        dict(k="Grade A or better", ok=row["grade"] in ("A+", "A"), v=row["grade"]),
        dict(k="Real pattern", ok=bool(SETUPS & b), v=", ".join(sorted(SETUPS & b)) or "none"),
        dict(k="Stop within 6%", ok=(p["risk"] or 1) <= MAX_RISK, v=f"{(p['risk'] or 0) * 100:.1f}%"),
        dict(k="At the trigger", ok=-0.01 <= to_trigger <= MAX_TO_TRIGGER,
             v=f"{to_trigger * 100:+.1f}%"),
        dict(k="Not extended", ok="EXT" not in b, v="extended" if "EXT" in b else "fine"),
        dict(k="No earnings in 7 days", ok="ER+" not in b, v="earnings soon" if "ER+" in b else "clear"),
        dict(k="Options tradeable", ok="THIN" not in b, v="OPT" if "OPT" in b else "ok"),
        # unknown sector (Nasdaq's "Miscellaneous" and friends) is neutral, not a fail;
        # a missing quadrant for a mapped sector means no rotation data, which does fail
        dict(k="Sector with you",
             ok=(quad in (GOOD_LONG if long else GOOD_SHORT)) if quad else (row.get("sector_etf") is None),
             v=quad or ("sector n/a" if row.get("sector_etf") is None else "no rotation data")),
        dict(k="Group not against you", ok=(grp is None) or (grp >= 50 if long else grp <= 50),
             v=f"rank {grp}" if grp else "unranked"),
    ]


def enrich(data: dict, rrg: dict | None, charts: Path | None = None) -> dict:
    quads = sector_quadrants(rrg)
    themes = {}
    for side in ("long", "short"):
        counts = {}
        for r in data.get(side, []):
            if SETUPS & set(r["badges"]):
                counts[r["industry"]] = counts.get(r["industry"], 0) + 1
        for ind, n in counts.items():
            if ind and n >= THEME_MIN:
                themes[(side, ind)] = n

    prime = []
    for side in ("long", "short"):
        for r in data.get(side, []):
            etf = SECTOR_ETF.get(r.get("sector") or "")
            quad = quads.get(etf) if etf else None
            r["sector_etf"], r["sector_quadrant"] = etf, quad
            r["plan"] = plan(r)
            if quad and quad in (GOOD_LONG if side == "long" else GOOD_SHORT):
                r["badges"].append("SEC")
            if (side, r["industry"]) in themes:
                r["badges"].append("THEME")
            if charts:
                tape(r, charts)
            r["badges"] = list(dict.fromkeys(r["badges"]))   # safe to re-run on the same file
            r["checks"] = checklist(r, quad)
            r["prime"] = all(c["ok"] for c in r["checks"])
            r["conf"] = confluence(r, (side, r["industry"]) in themes)
            r["bucket"] = bucket(r)
            if r["prime"]:
                prime.append(dict(t=r["t"], side=side, grade=r["grade"], score=r["score"],
                                  industry=r["industry"], plan=r["plan"],
                                  badges=[b for b in r["badges"] if b in SETUPS or b in ("SEC", "THEME", "LG", "WG", "OPT")]))
    prime.sort(key=lambda x: (x["score"], -abs(x["plan"]["risk"] or 1)), reverse=True)
    data["prime"] = prime
    # the ranked, bucketed lists the dashboard shows first
    order = dict(long=("leading", "improving", "earnings", "other"),
                 short=("lagging", "weakening", "earnings", "other"))
    data["confluence"] = {
        side: {b: sorted((dict(t=r["t"], conf=r["conf"], grade=r["grade"], score=r["score"],
                               industry=r["industry"], sector=r.get("sector") or "",
                               etf=r.get("sector_etf"), rvol=r.get("rvol"),
                               ema_dist=r.get("ema_dist"), chg1d=r.get("chg1d"), adr=r.get("adr"),
                               plan=r["plan"], prime=r["prime"],
                               badges=[x for x in r["badges"] if x in SETUPS or x in
                                       ("SEC", "THEME", "LG", "WG", "OPT", "THIN", "EXT", "ER+", "ER-1")])
                              for r in data.get(side, []) if r["bucket"] == b and SETUPS & set(r["badges"])),
                         key=lambda x: x["conf"], reverse=True)[:12]
               for b in order[side]}
        for side in ("long", "short")}
    data["themes"] = [dict(side=s, industry=i, n=n,
                           tickers=[r["t"] for r in data.get(s, [])
                                    if r["industry"] == i and SETUPS & set(r["badges"])][:8])
                      for (s, i), n in sorted(themes.items(), key=lambda kv: -kv[1])]
    data["legend"]["SEC"] = "Sector rotation is with you: Leading/Improving for longs, Lagging/Weakening for shorts"
    data["legend"]["THEME"] = f"{THEME_MIN}+ setups in this industry tonight: a group move, not a lone name"
    data["groups_of"]["SEC"] = "group"
    data["groups_of"]["THEME"] = "group"
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", default="site/scan.json")
    ap.add_argument("--rrg", default="site/rrg.json")
    ap.add_argument("--charts", default="site/charts")
    a = ap.parse_args()
    scan_p, rrg_p = Path(a.scan), Path(a.rrg)
    if not scan_p.exists():
        raise SystemExit("No scan.json yet; nothing to do.")
    data = json.loads(scan_p.read_text())
    rrg = json.loads(rrg_p.read_text()) if rrg_p.exists() else None
    data = enrich(data, rrg, Path(a.charts))
    scan_p.write_text(json.dumps(data, separators=(",", ":")))
    n = {s: sum(len(v) for v in data["confluence"][s].values()) for s in ("long", "short")}
    print(f"Confluence: {n['long']} long / {n['short']} short ranked | "
          f"Prime: {len(data['prime'])} ideas "
          f"({sum(1 for p in data['prime'] if p['side'] == 'long')} long), "
          f"{len(data['themes'])} themes")


if __name__ == "__main__":
    main()
