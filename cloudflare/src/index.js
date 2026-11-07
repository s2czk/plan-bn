import { buildPushPayload } from "@block65/webcrypto-web-push";

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };

function json(data, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(data), { status, headers: { ...JSON_HEADERS, ...extraHeaders } });
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin");
  const allowed = env.ALLOWED_ORIGIN || "";
  if (origin && origin !== allowed) return null;
  return {
    "access-control-allow-origin": origin || allowed,
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-allow-headers": "content-type, authorization",
    "access-control-max-age": "86400",
    "vary": "Origin",
  };
}

async function digestHex(value) {
  const bytes = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((part) => part.toString(16).padStart(2, "0")).join("");
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

async function listSubscriptions(kv) {
  const subscriptions = [];
  let cursor;
  do {
    const page = await kv.list({ prefix: "sub:", cursor, limit: 1000 });
    for (const key of page.keys) {
      const value = await kv.get(key.name, "json");
      if (value?.subscription?.endpoint) subscriptions.push({ key: key.name, ...value });
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return subscriptions;
}

function validSubscription(subscription) {
  if (
    !subscription ||
    typeof subscription.endpoint !== "string" ||
    typeof subscription.keys?.p256dh !== "string" ||
    typeof subscription.keys?.auth !== "string"
  ) return false;
  try {
    const endpoint = new URL(subscription.endpoint);
    if (endpoint.protocol !== "https:") return false;
    const host = endpoint.hostname.toLowerCase();
    return host === "fcm.googleapis.com" ||
      host.endsWith(".push.services.mozilla.com") ||
      host === "web.push.apple.com" ||
      host.endsWith(".notify.windows.com");
  } catch {
    return false;
  }
}

async function handleSubscribe(request, env) {
  if (!env.PUSH_KV) return json({ error: "Brak konfiguracji KV." }, 503);
  const data = await readJson(request);
  if (!validSubscription(data)) return json({ error: "Nieprawidłowa subskrypcja Push." }, 400);
  const id = await digestHex(data.endpoint);
  await env.PUSH_KV.put("sub:" + id, JSON.stringify({
    subscription: data,
    createdAt: new Date().toISOString(),
  }));
  return json({ ok: true });
}

async function handleUnsubscribe(request, env) {
  if (!env.PUSH_KV) return json({ error: "Brak konfiguracji KV." }, 503);
  const data = await readJson(request);
  if (typeof data?.endpoint !== "string" || !data.endpoint.startsWith("https://")) {
    return json({ error: "Nieprawidłowy endpoint." }, 400);
  }
  await env.PUSH_KV.delete("sub:" + await digestHex(data.endpoint));
  return json({ ok: true });
}

async function handleDispatch(request, env) {
  if (!env.PUSH_KV || !env.VAPID_PUBLIC_KEY || !env.VAPID_PRIVATE_KEY || !env.VAPID_SUBJECT) {
    return json({ error: "Brak konfiguracji Cloudflare Push." }, 503);
  }
  const expected = env.DISPATCH_TOKEN || "";
  const supplied = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!expected || supplied !== expected) return json({ error: "Nieprawidłowy token." }, 401);

  const data = await readJson(request);
  const notifications = Array.isArray(data?.notifications) ? data.notifications.slice(0, 50) : null;
  if (!notifications) return json({ error: "Oczekiwano tablicy notifications." }, 400);

  const subscriptions = await listSubscriptions(env.PUSH_KV);
  const vapid = {
    subject: env.VAPID_SUBJECT,
    publicKey: env.VAPID_PUBLIC_KEY,
    privateKey: env.VAPID_PRIVATE_KEY,
  };
  const result = { notifications: notifications.length, devices: subscriptions.length, sent: 0, skipped: 0, removed: 0, failed: 0 };

  for (const item of notifications) {
    if (typeof item?.id !== "string" || !item.id) continue;
    const markerSuffix = await digestHex(item.id);
    const bodyText = String(item.message || "W planie zajęć pojawiła się zmiana.");
    const pushData = JSON.stringify({
      title: String(item.title || "Zmiany w planie zajęć").slice(0, 120),
      body: bodyText.slice(0, 240),
      url: String(item.url || "./").slice(0, 500),
      tag: "plan-bn-" + markerSuffix.slice(0, 24),
    });

    for (const entry of subscriptions) {
      const marker = "sent:" + entry.key.slice(4) + ":" + markerSuffix;
      if (await env.PUSH_KV.get(marker)) {
        result.skipped++;
        continue;
      }
      try {
        const payload = await buildPushPayload(
          { data: pushData, options: { ttl: 86400 } },
          entry.subscription,
          vapid
        );
        const response = await fetch(entry.subscription.endpoint, payload);
        if (response.status === 404 || response.status === 410) {
          await env.PUSH_KV.delete(entry.key);
          result.removed++;
          continue;
        }
        if (!response.ok) {
          result.failed++;
          continue;
        }
        await env.PUSH_KV.put(marker, "1", { expirationTtl: 604800 });
        result.sent++;
      } catch (error) {
        result.failed++;
        console.error("Push delivery failed:", error?.message || String(error));
      }
    }
  }

  return json(result, result.failed ? 502 : 200);
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (!cors) return json({ error: "Niedozwolone źródło." }, 403);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const url = new URL(request.url);
    const route = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "GET" && route === "/health") {
      return json({ ok: true, service: "plan-bn-push" }, 200, cors);
    }
    if (request.method === "GET" && route === "/config") {
      return json({ publicVapidKey: env.VAPID_PUBLIC_KEY || "" }, 200, cors);
    }
    if (request.method === "POST" && route === "/subscribe") {
      return handleSubscribe(request, env).then((response) => addCors(response, cors));
    }
    if (request.method === "POST" && route === "/unsubscribe") {
      return handleUnsubscribe(request, env).then((response) => addCors(response, cors));
    }
    if (request.method === "POST" && route === "/dispatch") {
      return handleDispatch(request, env).then((response) => addCors(response, cors));
    }
    return json({ error: "Nie znaleziono endpointu." }, 404, cors);
  },
};

function addCors(response, cors) {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(cors)) headers.set(key, value);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}
