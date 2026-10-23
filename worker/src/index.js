/*
 * The download counter, at www.leongorecki.eu/evans/dl/.
 *
 *   /evans/dl/windows   the installer from the latest release
 *   /evans/dl/zip       the portable Windows zip
 *   /evans/dl/mac       the Apple Silicon disk image
 *   /evans/dl/count     the totals, as JSON
 *
 * A download is counted once per visitor per day: the visitor is a SHA-256
 * of the day, their IP, their browser and a secret salt, kept for two days
 * and then forgotten, so nobody can be followed from one day to the next.
 * Then it redirects to the file on GitHub. Bots and HEAD requests are sent on
 * without being counted. The zip counts as a Windows download.
 *
 * The file's address comes from GitHub's API, cached for ten minutes, so a
 * new release is picked up without redeploying. If GitHub does not answer,
 * the visitor goes to the release page instead of an error.
 */

const REPO = "leo-01000111/evans";
const RELEASES = `https://github.com/${REPO}/releases/latest`;

const FILES = {
  windows: { asset: /^Evans-Setup-[\d.]+\.exe$/, counter: "windows" },
  zip: { asset: /^Evans-windows\.zip$/, counter: "windows" },
  mac: { asset: /^Evans-[\d.]+-macos-arm64\.dmg$/, counter: "mac" },
};
const COUNTERS = ["windows", "mac"];

const BOT = /bot|crawl|spider|slurp|preview|monitor|headless|lighthouse/i;

export default {
  async fetch(request, env, ctx) {
    const what = new URL(request.url).pathname.replace(/^\/evans\/dl\/?/, "").replace(/\/$/, "");
    if (what === "count") return count(env);
    const file = FILES[what];
    if (!file) return new Response("Not found", { status: 404 });

    const target = await latest(file.asset, ctx);
    if (request.method === "GET" && !BOT.test(request.headers.get("User-Agent") || "")) {
      ctx.waitUntil(record(request, env, file.counter));
    }
    return Response.redirect(target, 302);
  },
};

/* The file's download address in the latest release, or the release page. */
async function latest(asset, ctx) {
  const cache = caches.default;
  const key = new Request(`https://evans-dl.internal/latest`);
  let release = await cache.match(key);
  if (!release) {
    try {
      const answer = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
        headers: { Accept: "application/vnd.github+json", "User-Agent": "evans-downloads" },
      });
      if (!answer.ok) return RELEASES;
      release = new Response(await answer.text(), {
        headers: { "Cache-Control": "max-age=600", "Content-Type": "application/json" },
      });
      ctx.waitUntil(cache.put(key, release.clone()));
    } catch {
      return RELEASES;
    }
  }
  const assets = (await release.json()).assets || [];
  const found = assets.find((a) => asset.test(a.name));
  return found ? found.browser_download_url : RELEASES;
}

async function record(request, env, counter) {
  const day = new Date().toISOString().slice(0, 10);
  const who = [day, request.headers.get("CF-Connecting-IP") || "",
               request.headers.get("User-Agent") || "", env.SALT].join("|");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(who));
  const hash = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const seen = `seen:${counter}:${hash}`;
  if (await env.DL.get(seen)) return;
  await env.DL.put(seen, "1", { expirationTtl: 2 * 86400 });
  const total = parseInt((await env.DL.get(`count:${counter}`)) || "0", 10);
  await env.DL.put(`count:${counter}`, String(total + 1));
}

async function count(env) {
  const body = {};
  for (const c of COUNTERS) body[c] = parseInt((await env.DL.get(`count:${c}`)) || "0", 10);
  body.total = COUNTERS.reduce((sum, c) => sum + body[c], 0);
  return new Response(JSON.stringify(body), {
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "max-age=60",
    },
  });
}
