// On every 15-minute candle close: check tonight's A / A+ setups and ping Discord the first
// time one CLOSES a 15m candle through its pivot (long) or trigger (short).
// Replaces the GitHub Actions alert job, whose 10-minute schedule GitHub kept dropping.
//
// Env (Netlify > Project configuration > Environment variables):
//   DISCORD_WEBHOOK_URL   where alerts go
//   DASH_USER, DASH_PASS  already set; used to read scan.json through the private gate
import { readFile } from "node:fs/promises";
import { getStore } from "@netlify/blobs";
import { candidates, check, embed, etNow, marketOpen, parseQuote, sessionFraction } from "../lib/alerts-core.mjs";

// UTC. Runs a minute after each 15m close (:01, :16, :31, :46) so the candle is final;
// filtered to 9:46-16:02 ET below, which covers both daylight and standard time.
export const config = { schedule: "1,16,31,46 13-21 * * 1-5" };

const env = n => process.env[n] || process.env[n.toLowerCase()];

// scan.json ships with the function (see netlify.toml included_files), so this never
// goes through the site's login gate. The HTTP fetch stays only as a last resort.
const SCAN_PATHS = ["site/scan.json", "./site/scan.json", "/var/task/site/scan.json",
                    new URL("../../site/scan.json", import.meta.url).pathname];

async function loadScan() {
  for (const p of SCAN_PATHS) {
    try {
      const raw = await readFile(p, "utf8");
      const data = JSON.parse(raw);
      console.log(`scan.json read from ${p} (as of ${data.as_of})`);
      return data;
    } catch { /* try the next location */ }
  }
  const base = process.env.URL || process.env.DEPLOY_PRIME_URL;
  const auth = "Basic " + Buffer.from(`${env("DASH_USER")}:${env("DASH_PASS")}`).toString("base64");
  const r = await fetch(`${base}/scan.json`, { headers: { Authorization: auth } });
  if (!r.ok) throw new Error(`no bundled scan.json and HTTP fallback gave ${r.status}`);
  console.log("scan.json read over HTTP fallback");
  return r.json();
}

async function quotes(tickers) {
  const out = {};
  const one = async t => {
    try {
      const r = await fetch(`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(t)}?range=1d&interval=15m`,
                            { headers: { "User-Agent": "Mozilla/5.0" } });
      if (r.ok) { const q = parseQuote(await r.json()); if (q) out[t] = q; }
    } catch { /* one bad symbol never stops the run */ }
  };
  for (let i = 0; i < tickers.length; i += 12) await Promise.all(tickers.slice(i, i + 12).map(one));
  return out;
}

export default async () => {
  const now = etNow();
  const live = marketOpen(now);
  const store = getStore("fifi-alerts");
  const state = (await store.get(now.date, { type: "json" })) || { date: now.date, fired: [] };
  const fired = new Set(state.fired.map(a => `${a.t}:${a.side}`));

  // The whole check runs even outside market hours, so "Run now" in the Netlify UI is a
  // full end-to-end test. Only the Discord post and the state write are gated on `live`.
  let scan;
  try {
    scan = await loadScan();
  } catch (e) {
    console.log(`SCAN FETCH FAILED: ${e.message} (URL=${process.env.URL}, user set=${!!env("DASH_USER")}, pass set=${!!env("DASH_PASS")})`);
    return new Response(`scan fetch failed: ${e.message}`, { status: 500 });
  }
  const rows = candidates(scan);
  const q = await quotes([...new Set(rows.map(r => r.t))]);
  const hits = check(rows, q, fired, sessionFraction(now)).map(a => ({ ...a, time: now.hhmm }));

  // Nearest few, so a quiet day is visibly quiet rather than ambiguous
  const near = rows.map(r => {
    const price = q[r.t]?.price;
    return price ? { t: r.t, side: r.side, away: +(((r.levels.pivot / price - 1) * 100) * (r.side === "long" ? 1 : -1)).toFixed(2) } : null;
  }).filter(Boolean).sort((a, b) => a.away - b.away).slice(0, 5);
  console.log(`${now.hhmm} ET live=${live} scan=${scan.as_of} watched=${rows.length} quoted=${Object.keys(q).length} `
    + `hits=${hits.map(h => h.t).join(",") || "none"} nearest=${near.map(n => `${n.t} ${n.away}%`).join(" | ")}`);

  if (!live) return new Response(`diagnostic run (market closed): watched ${rows.length}, quoted ${Object.keys(q).length}, would alert: ${hits.map(h => h.t).join(", ") || "none"}`);
  if (!hits.length) return new Response(`${now.hhmm} ET: ${rows.length} A/A+ watched, no 15m closes through`);

  const hook = env("DISCORD_WEBHOOK_URL");
  if (hook) {
    for (const a of hits) {
      await fetch(hook, { method: "POST", headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ embeds: [embed(a)] }) }).catch(() => {});
    }
  }
  if (!hook) console.log("DISCORD_WEBHOOK_URL is not set; alert was computed but not posted");
  state.fired.push(...hits);
  await store.setJSON(now.date, state);
  return new Response(`${now.hhmm} ET: ${hits.map(a => a.t).join(", ")} closed through`);
};
