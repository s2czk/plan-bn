import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

function createEnv() {
  const store = new Map();
  return {
    ALLOWED_ORIGIN: "https://plan.mandaro.eu",
    VAPID_PUBLIC_KEY: "public-vapid-key",
    VAPID_PRIVATE_KEY: "private-vapid-key",
    VAPID_SUBJECT: "mailto:szymon@mandaro.eu",
    DISPATCH_TOKEN: "secret-token",
    PUSH_KV: {
      async put(key, value) { store.set(key, value); },
      async get(key, format) {
        const value = store.get(key);
        if (value === undefined) return null;
        return format === "json" ? JSON.parse(value) : value;
      },
      async delete(key) { store.delete(key); },
      async list({ prefix }) {
        return { keys: [...store.keys()].filter((key) => key.startsWith(prefix)).map((name) => ({ name })), list_complete: true };
      },
      store,
    },
  };
}

test("health and config endpoints return CORS-enabled JSON", async () => {
  const env = createEnv();
  const health = await worker.fetch(new Request("https://worker.test/health", {
    headers: { Origin: "https://plan.mandaro.eu" },
  }), env);
  assert.equal(health.status, 200);
  assert.deepEqual(await health.json(), { ok: true, service: "plan-bn-push" });
  assert.equal(health.headers.get("access-control-allow-origin"), "https://plan.mandaro.eu");

  const config = await worker.fetch(new Request("https://worker.test/config", {
    headers: { Origin: "https://plan.mandaro.eu" },
  }), env);
  assert.equal(config.status, 200);
  assert.deepEqual(await config.json(), { publicVapidKey: "public-vapid-key" });
});

test("requests from a different website are rejected", async () => {
  const response = await worker.fetch(new Request("https://worker.test/config", {
    headers: { Origin: "https://evil.example" },
  }), createEnv());
  assert.equal(response.status, 403);
});

test("a valid device can subscribe and unsubscribe", async () => {
  const env = createEnv();
  const subscription = {
    endpoint: "https://fcm.googleapis.com/fcm/send/test-endpoint",
    expirationTime: null,
    keys: { p256dh: "p256dh-test", auth: "auth-test" },
  };
  const subscribe = await worker.fetch(new Request("https://worker.test/subscribe", {
    method: "POST",
    headers: { Origin: "https://plan.mandaro.eu", "Content-Type": "application/json" },
    body: JSON.stringify(subscription),
  }), env);
  assert.equal(subscribe.status, 200);
  assert.deepEqual(await subscribe.json(), { ok: true });
  assert.equal(env.PUSH_KV.store.size, 1);

  const unsubscribe = await worker.fetch(new Request("https://worker.test/unsubscribe", {
    method: "POST",
    headers: { Origin: "https://plan.mandaro.eu", "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  }), env);
  assert.equal(unsubscribe.status, 200);
  assert.deepEqual(await unsubscribe.json(), { ok: true });
  assert.equal(env.PUSH_KV.store.size, 0);
});

test("an invalid push endpoint is rejected", async () => {
  const response = await worker.fetch(new Request("https://worker.test/subscribe", {
    method: "POST",
    headers: { Origin: "https://plan.mandaro.eu", "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint: "https://localhost/private",
      keys: { p256dh: "test", auth: "test" },
    }),
  }), createEnv());
  assert.equal(response.status, 400);
});

test("authorized dispatch accepts an empty update", async () => {
  const response = await worker.fetch(new Request("https://worker.test/dispatch", {
    method: "POST",
    headers: {
      Origin: "https://plan.mandaro.eu",
      Authorization: "Bearer secret-token",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ notifications: [] }),
  }), createEnv());
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    notifications: 0, devices: 0, sent: 0, skipped: 0, removed: 0, failed: 0,
  });
});

test("push dispatch requires the private server token", async () => {
  const response = await worker.fetch(new Request("https://worker.test/dispatch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notifications: [] }),
  }), createEnv());
  assert.equal(response.status, 401);
});
