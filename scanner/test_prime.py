"""Prime filter rules: python scanner/test_prime.py"""
import copy

import prime

base = dict(t="AAA", side="long", grade="A", score=80, industry="Semiconductors", chg1d=0.012, adr=3.0,
            sector="Technology", price=100.0, badges=["VCP", "OPT"],
            grp={"rank": 80, "n": 12, "med": 70},
            levels=dict(pivot=102.0, stop=97.0))
rrg = {"items": [{"t": "XLK", "quadrant": "Leading"}, {"t": "XLP", "quadrant": "Lagging"}]}

def run(**over):
    r = copy.deepcopy(base); r.update(over)
    d = {"long": [r], "short": [], "legend": {}, "groups_of": {}}
    return prime.enrich(d, rrg)["long"][0]

ok = True
def check(name, got, want=True):
    global ok
    good = got == want
    print(("PASS" if good else "FAIL") + f"  {name}: {got}")
    ok &= good

good = run()
check("clean setup is prime", good["prime"])
check("2R target", good["plan"]["t2"], 112.0)
check("risk is 4.9%", round(good["plan"]["risk"] * 100, 1), 4.9)
check("sector badge added", "SEC" in good["badges"])

check("wide stop rejected", run(levels=dict(pivot=102.0, stop=88.0))["prime"], False)
check("too far from trigger rejected", run(levels=dict(pivot=112.0, stop=106.0))["prime"], False)
check("already extended rejected", run(badges=["VCP", "EXT"])["prime"], False)
check("earnings soon rejected", run(badges=["VCP", "ER+"])["prime"], False)
check("thin options rejected", run(badges=["VCP", "THIN"])["prime"], False)
check("B grade rejected", run(grade="B")["prime"], False)
check("no pattern rejected", run(badges=["OPT"])["prime"], False)
check("wrong sector rejected", run(sector="Consumer Staples")["prime"], False)
check("weak group rejected", run(grp={"rank": 20, "n": 9, "med": 30})["prime"], False)

# a short in a lagging sector is prime; the same short in a leading sector is not
sh = dict(base, side="short", sector="Consumer Staples", badges=["FLAG", "OPT"],
          grp={"rank": 15, "n": 8, "med": 20}, levels=dict(pivot=98.0, stop=103.0))
d = prime.enrich({"long": [], "short": [copy.deepcopy(sh)], "legend": {}, "groups_of": {}}, rrg)
check("short in lagging sector is prime", d["short"][0]["prime"])
check("short 2R target is lower", d["short"][0]["plan"]["t2"], 88.0)

# themes: three setups in one industry
rows = [dict(base, t=f"T{i}", badges=["VCP"]) for i in range(3)]
d = prime.enrich({"long": rows, "short": [], "legend": {}, "groups_of": {}}, rrg)
check("theme detected", d["themes"][0]["n"], 3)
check("theme badge on members", "THEME" in d["long"][0]["badges"])

d = prime.enrich({"long": [copy.deepcopy(base)], "short": [], "legend": {}, "groups_of": {}}, None)
check("no rrg: sector check fails safe", d["long"][0]["prime"], False)

# confluence score and bucketing
good = run()
check("confluence scored", 0 < good["conf"] <= 20)
check("leading sector bucket", good["bucket"], "leading")
check("earnings goes to its own bucket", run(badges=["VCP", "ER+"])["bucket"], "earnings")
check("weak setup scores lower than strong",
      run(score=55, grade="C", grp={"rank": 20, "n": 5, "med": 30})["conf"] < good["conf"])
d = prime.enrich({"long": [copy.deepcopy(base)], "short": [], "legend": {}, "groups_of": {}}, rrg)
check("ranked list built", d["confluence"]["long"]["leading"][0]["t"], "AAA")

# running twice must not duplicate badges
rows2 = [dict(base, t=f"T{i}", badges=["VCP"]) for i in range(3)]
d2 = {"long": rows2, "short": [], "legend": {}, "groups_of": {}}
prime.enrich(d2, rrg); prime.enrich(d2, rrg)
check("re-running does not duplicate badges", d2["long"][0]["badges"].count("THEME"), 1)

raise SystemExit(0 if ok else 1)
