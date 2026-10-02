// Pivot-alert logic shared by the Netlify functions. Pure functions, no I/O, so it can
// be tested in plain Node without Netlify.

export const GRADES = new Set(["A+", "A"]);   // only alert on these
export const MAX_WATCH = 60;                   // quotes per run stays well inside 30s
export const BAR_SECS = 15 * 60;               // alert on 15-minute candle closes

/** Eastern-time date, minutes since midnight and weekday, whatever the server clock. */
export function etNow(d = new Date()) {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour12: false, weekday: "short",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(d).map(x => [x.type, x.value]));
  return { date: `${p.year}-${p.month}-${p.day}`, mins: (Number(p.hour) % 24) * 60 + Number(p.minute),
           weekday: p.weekday, hhmm: `${String(Number(p.hour) % 24).padStart(2, "0")}:${p.minute}` };
}

export function marketOpen(t) {
  // 9:46 is the first close (the 9:30-9:45 candle); 16:02 catches the final 15:45-16:00 candle
  return !["Sat", "Sun"].includes(t.weekday) && t.mins >= 9 * 60 + 45 && t.mins <= 16 * 60 + 5;
}

/** Fraction of the regular session elapsed, for pacing volume. */
export function sessionFraction(t) {
  return Math.min(1, Math.max(0.02, (t.mins - (9 * 60 + 30)) / 390));
}

/** A and A+ setups from both sides of tonight's scan, best first. */
export function candidates(scan) {
  const rows = [];
  for (const side of ["long", "short"]) {
    for (const r of scan?.[side] || []) {
      if (GRADES.has(r.grade) && r.levels?.pivot) rows.push({ ...r, side });
    }
  }
  rows.sort((a, b) => b.score - a.score);
  return rows.slice(0, MAX_WATCH);
}

/**
 * Which rows CLOSED a 15-minute candle through their level: longs closing at or above the
 * pivot, shorts closing at or below the trigger. Intrabar pokes that fade don't count.
 * `quotes` maps ticker -> {price, high, low, volume, bar} where price is the last
 * completed candle's close. `fired` is a Set of "TICKER:side" already alerted today.
 */
export function check(rows, quotes, fired, frac) {
  const out = [];
  for (const r of rows) {
    const key = `${r.t}:${r.side}`, q = quotes[r.t];
    if (fired.has(key) || !q || !q.price) continue;
    const level = r.levels.pivot, long = r.side === "long";
    const hit = long ? q.price >= level : q.price <= level;
    if (!hit) continue;
    const pace = r.avgv && q.volume ? q.volume / r.avgv / frac : null;
    out.push({ t: r.t, side: r.side, grade: r.grade, score: r.score, level, price: round(q.price), bar: q.bar,
               stop: r.levels.stop, pace: pace ? round(pace) : null,
               setups: (r.badges || []).filter(b => SETUPS.has(b)) });
  }
  return out;
}

export const SETUPS = new Set(["VCP", "FLAG", "HTF", "WBO", "WPV", "WVCP", "WFLAG", "3WT"]);
const round = x => Math.round(x * 100) / 100;

/** Discord embed for one alert. */
export function embed(a) {
  const up = a.side === "long";
  const risk = Math.abs(a.price - a.stop) / a.price * 100;
  return {
    title: `${up ? "🟢" : "🔴"} ${a.t} ${a.grade} closed ${up ? "above pivot" : "below trigger"} $${a.level}`,
    description: `15m close $${a.price}${a.bar ? ` (${a.bar} candle)` : ""} · stop $${a.stop} (${risk.toFixed(1)}% risk)`
      + (a.setups.length ? ` · ${a.setups.join(" ")}` : "")
      + (a.pace ? `\nVolume pace ${a.pace}x${a.pace >= 1.5 ? " ✅" : ""}` : ""),
    color: up ? 0x00e676 : 0xff5252,
    url: `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(a.t.replace("-", "."))}`,
  };
}

/**
 * From a Yahoo 15-minute chart response, the last COMPLETED candle's close (a candle still
 * forming is ignored), plus day high/low and cumulative volume.
 */
export function parseQuote(json, nowSecs = Date.now() / 1000) {
  const res = json?.chart?.result?.[0];
  const ts = res?.timestamp, q = res?.indicators?.quote?.[0];
  if (!ts || !q) return null;
  let i = ts.length - 1;
  while (i >= 0 && (ts[i] + BAR_SECS > nowSecs + 5 || q.close[i] == null)) i--;
  if (i < 0) return null;
  const highs = q.high.slice(0, i + 1).filter(x => x != null), lows = q.low.slice(0, i + 1).filter(x => x != null);
  const bar = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false })
    .format(new Date(ts[i] * 1000));
  return { price: q.close[i], high: Math.max(...highs), low: Math.min(...lows),
           volume: q.volume.slice(0, i + 1).reduce((a, v) => a + (v || 0), 0), bar };
}
