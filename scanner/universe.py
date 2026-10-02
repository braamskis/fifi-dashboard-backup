"""Universe, company metadata (sector / industry / market cap) and daily prices."""
from __future__ import annotations

import io
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

from core import MIN_BARS

UA = {"User-Agent": "Mozilla/5.0 (FiFi's Dashboard)"}
SKIP_RE = re.compile(r"\b(warrants?|units?|rights?|preferred|notes? due|debentures?|"
                     r"subordinated|when issued)\b|%", re.I)


# ------------------------------------------------------------------ universe
def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


EXCH = {"A": "AMEX", "N": "NYSE", "P": "AMEX", "Z": "CBOE", "V": "IEX"}   # TradingView prefixes


def full_market_universe() -> dict[str, str]:
    """Every NYSE / Nasdaq / NYSE American common stock + ADR, minus ETFs, test
    issues, warrants, units, rights and preferreds. Returns {ticker: exchange}."""
    base = "https://www.nasdaqtrader.com/dynamic/SymDir/"
    out: dict[str, str] = {}

    nas = pd.read_csv(io.StringIO(_fetch(base + "nasdaqlisted.txt")), sep="|")
    nas = nas[nas["Symbol"].notna() & ~nas["Symbol"].astype(str).str.startswith("File Creation")]
    nas = nas[(nas["ETF"] == "N") & (nas["Test Issue"] == "N")]
    for sym, name in zip(nas["Symbol"], nas["Security Name"]):
        if _keep(sym, name):
            out[_yf(sym)] = "NASDAQ"

    oth = pd.read_csv(io.StringIO(_fetch(base + "otherlisted.txt")), sep="|")
    oth = oth[oth["ACT Symbol"].notna() & ~oth["ACT Symbol"].astype(str).str.startswith("File Creation")]
    oth = oth[(oth["ETF"] == "N") & (oth["Test Issue"] == "N")]
    for sym, name, ex in zip(oth["ACT Symbol"], oth["Security Name"], oth["Exchange"]):
        if _keep(sym, name):
            out[_yf(sym)] = EXCH.get(str(ex), "")

    return dict(sorted(out.items()))


def fetch_meta(cache: Path) -> dict[str, dict]:
    """Sector, industry and market cap for every US stock in one request (Nasdaq's
    public screener). Cached in the repo so a failed request falls back to the last copy."""
    try:
        req = urllib.request.Request(
            "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&download=true",
            headers={**UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read())["data"]["rows"]
        meta = {}
        for row in rows:
            try:
                mcap = float(str(row.get("marketCap") or 0).replace(",", "") or 0)
            except ValueError:
                mcap = 0.0
            meta[_yf(row["symbol"])] = dict(sector=row.get("sector") or "", industry=row.get("industry") or "",
                                            mcap=mcap or None)
        if len(meta) > 1000:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(meta, separators=(",", ":")))
            return meta
    except Exception as e:
        print(f"  meta fetch failed ({e}); using cache", file=sys.stderr)
    return json.loads(cache.read_text()) if cache.exists() else {}


def _keep(sym, name) -> bool:
    sym, name = str(sym), str(name).lower()
    if not sym or "$" in sym or len(sym) > 6:
        return False
    return not SKIP_RE.search(name)


def _yf(sym: str) -> str:
    return str(sym).strip().upper().replace(".", "-")   # BRK.B -> BRK-B for Yahoo


def read_list(path: str | None) -> list[str]:
    if not path or not Path(path).exists():
        return []
    syms = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#")[0].strip()
        for tok in line.replace(",", " ").split():
            tok = tok.split(":")[-1]            # accepts TradingView "NASDAQ:AMD"
            if tok:
                syms.append(_yf(tok.lstrip("$")))
    return list(dict.fromkeys(syms))


# ------------------------------------------------------------------ prices
def download(tickers: list[str], chunk: int = 200) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    frames: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(batch, period="2y", interval="1d", auto_adjust=True,
                                 group_by="ticker", threads=True, progress=False)
                break
            except Exception as e:  # network hiccup / rate limit
                print(f"  batch {i // chunk} attempt {attempt + 1} failed: {e}", file=sys.stderr)
                time.sleep(10 * (attempt + 1))
        if df is None or df.empty:
            continue
        multi = isinstance(df.columns, pd.MultiIndex)
        level0 = set(df.columns.get_level_values(0)) if multi else set()
        for t in batch:
            if multi:
                if t not in level0:
                    continue
                sub = df[t]
            else:
                sub = df
            sub = sub.dropna(subset=["Close"])
            if len(sub) >= MIN_BARS:
                frames[t] = sub
        print(f"  downloaded {min(i + chunk, len(tickers))}/{len(tickers)}  usable {len(frames)}")
        time.sleep(1.5)
    return frames


# ------------------------------------------------------------------ data source
download_yahoo = download          # the Yahoo downloader above, kept as the fallback


def download(tickers: list[str], chunk: int = 200) -> dict[str, pd.DataFrame]:   # noqa: F811
    """Daily bars: Massive when MASSIVE_API_KEY is set (one call per trading day covers
    the whole market), otherwise Yahoo. Falls back to Yahoo if Massive fails or returns
    too little, so a bad night at one provider does not skip the scan."""
    import massive_data
    if massive_data.api_key():
        try:
            frames = massive_data.download(tickers)
            usable = {t: df for t, df in frames.items() if len(df) >= MIN_BARS}
            if len(usable) >= 100:
                return usable
            print(f"  massive returned only {len(usable)} usable tickers; falling back to Yahoo",
                  file=sys.stderr)
        except Exception as e:
            print(f"  massive failed ({e}); falling back to Yahoo", file=sys.stderr)
    return download_yahoo(tickers, chunk)
