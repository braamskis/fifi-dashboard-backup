# FiFi's Dashboard

Personal nightly scanner for the whole US market: long and short setups, daily and weekly, graded A+ to F, with charts, key levels, options checks, group strength, a market regime light, a scorecard of how past setups worked, and intraday pivot alerts to Discord.

```
scanner/scan.py           nightly scan: universe -> prices -> both sides -> site/scan.json + site/charts/
scanner/core.py           indicators, pattern detectors, weekly setups, RS line, key levels, TQE grade
scanner/universe.py       full-market ticker list, sector / industry / market cap, price download
scanner/options_data.py   options liquidity, IV / IV rank, unusual activity
scanner/scorecard.py      saved scans + what happened after each setup
scanner/alerts.py         intraday pivot alerts (Discord)
scanner/test_*.py         tests; run before every scan
scanner/watchlist.txt     your list: always scanned, tagged WL
scanner/data/             cached metadata and IV history (committed by the workflow)
site/                     the dashboard Netlify publishes
```

## Set up
1. Push this folder to a new GitHub repo (private is fine).
2. Repo Settings -> Actions -> General -> Workflow permissions -> "Read and write". Save.
3. Netlify -> Add new site -> Import from GitHub -> pick the repo. Leave the build command empty.
4. Discord alerts: in your Discord server, Channel settings -> Integrations -> Webhooks -> New webhook -> Copy URL. In GitHub: Settings -> Secrets and variables -> Actions -> New secret named `DISCORD_WEBHOOK_URL`, paste the URL.
5. First run: Actions -> FiFi's Dashboard scan -> Run workflow, set backfill to `60`. That rebuilds 60 days of past scans from price history so the scorecard has data on day one. It takes 30-60 minutes; later nightly runs take about 15-25.

After that the scan runs every weekday after the close and alerts run every 10 minutes during market hours.

## Members-only access (Whop)
The site is gated by `netlify/edge-functions/private.ts`: visitors click "Sign in with Whop", and only users with an active membership on one of your Whop products get in. Membership is re-checked hourly, so cancelled members lose access.

In Whop's developer dashboard, create an OAuth app with redirect URI `https://YOUR-SITE/auth/callback` (add the `.netlify.app` URL too if you use it), and create an API key. Then set these Netlify environment variables and redeploy:

| Variable | What |
|---|---|
| `WHOP_CLIENT_ID`, `WHOP_CLIENT_SECRET` | the OAuth app's credentials |
| `WHOP_API_KEY` | server-side API key, used for the membership check |
| `WHOP_PRODUCT_IDS` | comma-separated `prod_...` ids that grant access |
| `WHOP_JOIN_URL` | your Whop page, where non-members are sent to buy |
| `SESSION_SECRET` | long random string that signs the session cookie |
| `INTERNAL_TOKEN` | long random string; the alert function uses it to read `scan.json` |
| `SITE_URL` | optional, your public URL (defaults to the request's origin) |

Until all required variables are set the site returns 503 (locked). Whop endpoint URLs are constants at the top of `private.ts`; check them against Whop's current docs if sign-in fails.

Cost: free on a public repo. On a private repo the two workflows use roughly 1,300 of GitHub's 2,000 free monthly minutes, mostly alerts. Change the alerts cron to `*/15` to cut that by a third.

## Universe
Every NYSE, Nasdaq and NYSE American common stock and ADR (Nasdaq's symbol directory), minus ETFs, warrants, units, rights and preferreds. Filtered to price >= $10 and 50-day average dollar volume >= $20M. Sector, industry and market cap come from Nasdaq's public screener in one request, cached in `scanner/data/meta.json`. Paste a TradingView watchlist export into `scanner/watchlist.txt` to always include those names.

## Which stocks make the lists
**Longs:** Minervini trend template (8 rules, RS 70+), or a weekly setup (WBO / WPV / WVCP) in stage 2 with RS 60+. The weekly route catches names like INTC building a base after a big run, before they re-qualify for the template.

**Shorts:** exactly the same rules run on the upside-down chart (price becomes 1/price). A downtrend then looks like an uptrend, a bear flag like a bull flag, a breakdown like a breakout, so every detector and the grade work unchanged. Candidates must be below their 50- and 200-day averages. Shorts need RS 30 or lower (weakness rank 70+).

## Badges
| Badge | Rule |
|---|---|
| VCP | Base from the 90-day high. 2+ pullbacks, each 10%+ shallower than the last; first <= 35% and >= 2x the last; last <= 10% (2 ADRs, max 12%); volume drying up; price 6% below to 3% above the pivot. Shorts: bounces getting smaller over the trigger |
| FLAG | 30%+ run into a high 4-25 days ago, flag < 25% deep and < half the run, last 5 days within 2.5 ADRs, lighter volume. Shorts: bear flag |
| HTF | 90%+ run in 40 days or less, then a flag < 25% deep (longs only) |
| WBO | Weekly breakout: this week closes through the pivot (highest weekly high of the prior 8 weeks), in the upper half of its range, with volume pacing at or above the 10-week average. Needs a 5-52 week base no deeper than 45%, price above the 10-week MA and a rising 40-week MA |
| WPV | At the weekly pivot: a strong up week pressing the pivot (high within 1%) without closing through yet |
| WVCP / WFLAG | The VCP and flag detectors run on weekly bars with weekly settings |
| 3WT, NR7, ID | 3 weekly closes within 1.5%; narrowest range of 7 days; inside day |
| RSNH | RS line (price / SPY) at a 52-week high. Shorts: 52-week low |
| RSBP | RS line at a new high while price is more than 5% below its high: the early tell |
| KQ, ON, 97C | Qullamaggie momentum leader, O'Neil-style leader (technical only), RS 97+ (longs) |
| LG / WG | Industry in the top / bottom 20% by group RS |
| EMA | Price > 8 > 21 > 50 EMA (shorts: the reverse) |
| SB4 / SD4, SBW / SDW | Up (down) 4%+ today on higher volume; up 20% (down 17%) in 5 days |
| PP / DV | Pocket pivot; down day on volume above any up day of the last 10 |
| 9M, HV, LQ | 9M+ shares today; highest volume in a year; $100M+/day and up 30%+ in 6 months |
| 52W / 52L, DB / BD | New 52-week high / low; box breakout / breakdown in the last 5 days |
| OPT / THIN | Options easy to trade (5K+ OI, ATM spread <= 10%, weeklies) / hard to trade |
| UOA | Unusual options activity on your side: calls for longs, puts for shorts |
| ER-1 / ER+ | Earnings last session / within 7 days |
| EXT | 7+ ADRs from the 50 SMA |
| NEW, WL, TRG | First day on the scan; on your watchlist; triggered today (from alerts) |

**Key levels:** weekly open (drawn on the daily chart), prior month high/low, and the nearest unfilled daily gaps, shown in each stock's levels.

**Stage:** 2A/2B = early/late uptrend (under/over 13 weeks), 4A/4B = the same for downtrends.

**RS:** 40% 3-month + 20% each 6, 9, 12-month return, percentile vs the liquid pool, 1-99.

**TQE grade:** RS 25, distance to pivot 20, 10-day range vs ADR 20, volume dry-up 10, extension from the 21 EMA 15, EMA stack 10, then +/-5 for group strength. A+ 85+, A 75+, B 65+, C 55+, D 45+. Weights live in `core.grade()`; tune them once the scorecard tells you what works.

## Options
For the top 80 of each side, from Yahoo option chains out to 45 days: ATM implied volatility, 20-day realized volatility, IV/HV, total open interest and volume, ATM bid/ask spread, weekly expirations, and share of premium in calls. **IV rank** is built from the scan's own nightly IV history (stored in `scanner/data/iv_history.json`), so it shows "building" for the first 20 scans. **Unusual activity** = a contract trading 500+ contracts, at least 2x its open interest, with $100K+ premium. It's an end-of-day snapshot and Yahoo doesn't say whether prints were bought or sold, so it's a flag to look closer, not a signal.

## Scorecard
Every scan is saved slim in `site/history/`. Each night every saved setup is replayed:
- **Triggered:** price reached the pivot (short: trigger) within 10 sessions. Entry = pivot, or the open if it gapped through.
- **R:** exit at the stop (or the gap open past it), else the close 20 sessions after entry, in multiples of entry-to-stop risk.
- **Hit 2R:** reached 2x risk in your favor at any point. **10-day:** move from the scan-day close.
Broken out by side, grade and pattern. The first months of backfilled history are a reasonable start, but small samples mislead.

## Alerts
Every 10 minutes from 9:35 AM to 4:00 PM ET, `alerts.py` checks A+/A grades and anything with a setup badge (both sides, top 80). It alerts once per stock per day when the day's high reaches the pivot and price is still within 0.5% of it (shorts: the day's low and the trigger). The message includes stop, risk and volume pace; 1.5x+ pace is what you want on a real breakout. Triggered names show at the top of the dashboard and get a TRG badge. Yahoo intraday can lag a few minutes and GitHub sometimes starts scheduled runs late, so these are "go look now" pings. For tick-accurate alerts, set TradingView alerts on the pivots of the names you care about.

## Dashboard
Longs, Shorts, Groups (strongest and weakest industries; tap one to filter) and Scorecard. The regime light is green/yellow/red from SPY and QQQ vs their 21 EMA and 50 SMA plus breadth; the page opens on Shorts when it's red. Each stock has Daily and Weekly charts (candles, EMAs or 10/20/40-week MAs, RS line band, pattern markers, pivot/stop, weekly open) and a TradingView tab. **Export to TradingView** downloads the current list as a watchlist file (TradingView -> watchlist menu -> Import list).

## Run locally
```
pip install -r scanner/requirements.txt
python scanner/scan.py                     # full scan
python scanner/scan.py --backfill 60       # plus 60 days of history
python scanner/scan.py --demo --out /tmp/demo/scan.json   # offline, synthetic data
cd scanner && python test_patterns.py && python test_alerts.py
```

Data: Yahoo Finance via yfinance (free, unofficial) and Nasdaq's public symbol and screener files. For more reliable data, swap `universe.download()` for Massive (Polygon) Starter at $29/month; nothing else changes.
