// Private gate for FiFi's Dashboard: every page and data file needs the username and
// password stored in Netlify env vars DASH_USER and DASH_PASS (either case). Runs before
// anything is served, on every URL of the site (custom domain, .netlify.app, previews).
import type { Config, Context } from "https://edge.netlify.com";

const REALM = "FiFi's Dashboard";

function env(name: string): string | undefined {
  return Netlify.env.get(name) || Netlify.env.get(name.toLowerCase());
}

function same(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

export default async (req: Request, context: Context) => {
  const user = env("DASH_USER");
  const pass = env("DASH_PASS");
  if (!user || !pass) {
    return new Response("Locked. Set DASH_USER and DASH_PASS in Netlify, then redeploy.", { status: 503 });
  }
  const [scheme, encoded] = (req.headers.get("authorization") || "").split(" ");
  if (scheme === "Basic" && encoded) {
    let decoded = "";
    try { decoded = atob(encoded); } catch { /* bad header */ }
    const i = decoded.indexOf(":");
    if (i > 0 && same(decoded.slice(0, i), user) && same(decoded.slice(i + 1), pass)) {
      const res = await context.next();
      const out = new Response(res.body, res);
      out.headers.set("X-Robots-Tag", "noindex, nofollow");
      out.headers.set("Cache-Control", "private, no-cache");
      return out;
    }
  }
  return new Response("Private.", {
    status: 401,
    headers: { "WWW-Authenticate": `Basic realm="${REALM}", charset="UTF-8"`, "X-Robots-Tag": "noindex" },
  });
};

export const config: Config = { path: "/*" };
