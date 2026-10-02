// Members-only gate for FiFi's Dashboard: "Sign in with Whop", then a paid-membership check.
// Runs before anything is served, on every URL of the site (custom domain, .netlify.app, previews).
//
// Flow: /auth/login -> Whop OAuth (PKCE) -> /auth/callback -> Whop user id -> access check
// against WHOP_PRODUCT_IDS using the server-side API key -> signed HttpOnly session cookie.
// The cookie is re-checked against Whop every RECHECK_SECONDS, so cancelled members lose access.
//
// Env (Netlify > Project configuration > Environment variables):
//   WHOP_CLIENT_ID, WHOP_CLIENT_SECRET   OAuth app from the Whop developer dashboard
//   WHOP_API_KEY                         server-side API key (membership check)
//   WHOP_PRODUCT_IDS                     comma-separated prod_... ids that grant access
//   WHOP_JOIN_URL                        where non-members are sent to buy (your Whop page)
//   SESSION_SECRET                       long random string, signs the session cookie
//   INTERNAL_TOKEN                       long random string, lets the alert function fetch scan.json
//   SITE_URL                             optional, e.g. https://dash.example.com (else the request origin)
import type { Config, Context } from "https://edge.netlify.com";

const WHOP_AUTHORIZE = "https://api.whop.com/oauth/authorize";
const WHOP_TOKEN = "https://api.whop.com/oauth/token";
const WHOP_USERINFO = "https://api.whop.com/oauth/userinfo";
const WHOP_ACCESS = (userId: string, resource: string) =>
  `https://api.whop.com/api/v1/users/${encodeURIComponent(userId)}/access/${encodeURIComponent(resource)}`;

const COOKIE = "fifi_session";
const OAUTH_COOKIE = "fifi_oauth";
const SESSION_SECONDS = 60 * 60 * 24 * 7;   // sign in again after a week
const RECHECK_SECONDS = 60 * 60;            // re-verify membership hourly

const enc = new TextEncoder();
// TEMPORARY, FOR TESTING ONLY: values pasted here are used when the Netlify env var of the same
// name is unset. They live in git history once committed. Before going live, empty this block,
// set the real values in Netlify env vars, and rotate the client secret.
const TEST_CONFIG: Record<string, string> = {
  WHOP_CLIENT_ID: "app_xi5gOpJ4VUOfqU",
  WHOP_CLIENT_SECRET: "apik_WGwaw9gNRumXh_A2178259_C_36b5aa9bfbcfb4db73857c956dd4655e81817c16a43edb8f747bbb031791db",
  WHOP_API_KEY: "apik_XgfqTWnKWkMRU_C4045024_C_b02d1f0d1466f4fe78bcbb79a1592a2cc36781979133c21bf486364098ddc3",
  WHOP_PRODUCT_IDS: "prod_MatOC5m0qlB9J",
};
const env = (n: string) => Netlify.env.get(n) || Netlify.env.get(n.toLowerCase()) || TEST_CONFIG[n] || undefined;
const now = () => Math.floor(Date.now() / 1000);

const b64u = (b: ArrayBuffer | Uint8Array) =>
  btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64u = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));

async function hmac(data: string): Promise<string> {
  const key = await crypto.subtle.importKey("raw", enc.encode(env("SESSION_SECRET")!),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return b64u(await crypto.subtle.sign("HMAC", key, enc.encode(data)));
}

function same(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function sign(payload: Record<string, unknown>): Promise<string> {
  const body = b64u(enc.encode(JSON.stringify(payload)));
  return `${body}.${await hmac(body)}`;
}

async function verify(token: string | undefined): Promise<Record<string, any> | null> {
  if (!token) return null;
  const [body, mac] = token.split(".");
  if (!body || !mac || !same(mac, await hmac(body))) return null;
  try { return JSON.parse(new TextDecoder().decode(unb64u(body))); } catch { return null; }
}

function cookies(req: Request): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of (req.headers.get("cookie") || "").split(";")) {
    const i = part.indexOf("=");
    if (i > 0) out[part.slice(0, i).trim()] = part.slice(i + 1).trim();
  }
  return out;
}

const setCookie = (name: string, value: string, maxAge: number) =>
  `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;

function origin(req: Request): string {
  return (env("SITE_URL") || new URL(req.url).origin).replace(/\/$/, "");
}

const page = (title: string, body: string, status = 200, headers: HeadersInit = {}) =>
  new Response(`<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<style>body{font:16px/1.5 system-ui,sans-serif;background:#0b0e14;color:#e6e8ee;display:grid;place-items:center;min-height:100vh;margin:0}
main{max-width:380px;padding:32px;text-align:center}a.btn{display:inline-block;margin-top:16px;padding:12px 22px;border-radius:8px;
background:#fa4616;color:#fff;text-decoration:none;font-weight:600}a.sub{display:block;margin-top:14px;color:#8b93a7;font-size:14px}</style>
<main>${body}</main>`, { status, headers: { "Content-Type": "text/html; charset=utf-8", "X-Robots-Tag": "noindex", "Cache-Control": "no-store", ...headers } });

const signInPage = (note = "") => page("FiFi's Dashboard",
  `<h1>FiFi's Dashboard</h1><p>Members only.${note ? `<br>${note}` : ""}</p><a class="btn" href="/auth/login">Sign in with Whop</a>`, 401);

const notMemberPage = () => page("Members only",
  `<h1>Members only</h1><p>This Whop account doesn't have an active membership.</p>
<a class="btn" href="${env("WHOP_JOIN_URL") || "https://whop.com"}">Join on Whop</a><a class="sub" href="/auth/logout">Use a different account</a>`, 403,
  { "Set-Cookie": setCookie(COOKIE, "", 0) });

// True if the Whop user holds any of the allowed products. Fails closed on any error.
async function isMember(userId: string): Promise<boolean> {
  const products = (env("WHOP_PRODUCT_IDS") || "").split(",").map(s => s.trim()).filter(Boolean);
  if (!products.length) return false;
  for (const product of products) {
    try {
      const r = await fetch(WHOP_ACCESS(userId, product), { headers: { Authorization: `Bearer ${env("WHOP_API_KEY")}` } });
      if (r.ok && (await r.json()).has_access === true) return true;
    } catch { /* treat as no access */ }
  }
  return false;
}

async function login(req: Request): Promise<Response> {
  const verifier = b64u(crypto.getRandomValues(new Uint8Array(32)));
  const state = b64u(crypto.getRandomValues(new Uint8Array(16)));
  const nonce = b64u(crypto.getRandomValues(new Uint8Array(16)));
  const challenge = b64u(await crypto.subtle.digest("SHA-256", enc.encode(verifier)));
  const url = new URL(WHOP_AUTHORIZE);
  url.search = new URLSearchParams({
    response_type: "code", client_id: env("WHOP_CLIENT_ID")!, redirect_uri: `${origin(req)}/auth/callback`,
    scope: "openid", state, nonce, code_challenge: challenge, code_challenge_method: "S256",
  }).toString();
  const tmp = await sign({ state, verifier, exp: now() + 600 });
  return new Response(null, { status: 302, headers: { Location: url.toString(), "Set-Cookie": setCookie(OAUTH_COOKIE, tmp, 600), "Cache-Control": "no-store" } });
}

async function callback(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const tmp = await verify(cookies(req)[OAUTH_COOKIE]);
  if (!tmp || tmp.exp < now() || !url.searchParams.get("code") || !same(String(url.searchParams.get("state")), tmp.state)) {
    return signInPage("That sign-in expired. Try again.");
  }
  const tokenRes = await fetch(WHOP_TOKEN, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code", code: url.searchParams.get("code")!, redirect_uri: `${origin(req)}/auth/callback`,
      client_id: env("WHOP_CLIENT_ID")!, client_secret: env("WHOP_CLIENT_SECRET")!, code_verifier: tmp.verifier,
    }),
  });
  if (!tokenRes.ok) return signInPage("Whop sign-in failed. Try again.");
  const { access_token } = await tokenRes.json();
  const infoRes = await fetch(WHOP_USERINFO, { headers: { Authorization: `Bearer ${access_token}` } });
  const sub = infoRes.ok ? (await infoRes.json()).sub : null;
  if (!sub) return signInPage("Couldn't read your Whop account. Try again.");
  if (!(await isMember(sub))) return notMemberPage();
  const session = await sign({ sub, iat: now(), chk: now() });
  const headers = new Headers({ Location: "/", "Cache-Control": "no-store" });
  headers.append("Set-Cookie", setCookie(COOKIE, session, SESSION_SECONDS));
  headers.append("Set-Cookie", setCookie(OAUTH_COOKIE, "", 0));
  return new Response(null, { status: 302, headers });
}

export default async (req: Request, context: Context) => {
  const missing = ["WHOP_CLIENT_ID", "WHOP_CLIENT_SECRET", "WHOP_API_KEY", "WHOP_PRODUCT_IDS", "SESSION_SECRET", "INTERNAL_TOKEN"].filter(n => !env(n));
  if (missing.length) return new Response(`Locked. Set ${missing.join(", ")} in Netlify, then redeploy.`, { status: 503 });

  const { pathname } = new URL(req.url);
  if (pathname === "/auth/login") return login(req);
  if (pathname === "/auth/callback") return callback(req);
  if (pathname === "/auth/logout") {
    return new Response(null, { status: 302, headers: { Location: "/", "Set-Cookie": setCookie(COOKIE, "", 0) } });
  }

  // Server-to-server: the alert function reads scan.json with the internal token.
  const internal = req.headers.get("x-internal-token");
  let session = await verify(cookies(req)[COOKIE]);
  let refreshed: string | null = null;
  if (internal && same(internal, env("INTERNAL_TOKEN")!)) {
    session = { sub: "internal", iat: now(), chk: now() };
  } else if (session && now() - session.iat > SESSION_SECONDS) {
    session = null;
  } else if (session && now() - session.chk > RECHECK_SECONDS) {
    if (!(await isMember(session.sub))) return notMemberPage();
    session.chk = now();
    refreshed = await sign(session);
  }
  if (!session) {
    // Data requests get a plain 401 so the page's fetch() fails cleanly; pages get the sign-in screen.
    return /\.(json|js|css|png|svg|ico)$/.test(pathname) || pathname.startsWith("/api/")
      ? new Response("Private.", { status: 401, headers: { "X-Robots-Tag": "noindex" } })
      : signInPage();
  }

  const res = await context.next();
  const out = new Response(res.body, res);
  out.headers.set("X-Robots-Tag", "noindex, nofollow");
  out.headers.set("Cache-Control", "private, no-cache");
  if (refreshed) out.headers.append("Set-Cookie", setCookie(COOKIE, refreshed, SESSION_SECONDS));
  return out;
};

export const config: Config = { path: "/*" };
