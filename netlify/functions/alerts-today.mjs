// Today's triggered alerts, for the dashboard's "Triggered today" line and TRG badges.
// Sits behind the same private gate as the rest of the site.
import { getStore } from "@netlify/blobs";
import { etNow } from "../lib/alerts-core.mjs";

export const config = { path: "/api/alerts" };

export default async () => {
  const date = etNow().date;
  const data = (await getStore("fifi-alerts").get(date, { type: "json" })) || { date, fired: [] };
  return Response.json(data, { headers: { "Cache-Control": "no-cache" } });
};
