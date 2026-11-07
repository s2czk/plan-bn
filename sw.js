const CACHE_NAME = "pans-plan-shell-v2";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg", "./push-config.js"];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;

  const url = new URL(request.url);
  const isLiveData = url.pathname.endsWith("/schedule.json") || url.pathname.endsWith("/notifications.json");

  if (isLiveData) {
    event.respondWith(
      fetch(request).then(response => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
        }
        return response;
      }).catch(() => caches.match(request))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) {
        const copy = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
      }
      return response;
    }))
  );
});

self.addEventListener("push", event => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch (_) {}
  const title = payload.title || "Zmiana w planie PANS";
  const options = {
    body: payload.body || "W planie zajęć pojawiła się zmiana.",
    icon: "./icon.svg",
    badge: "./icon.svg",
    data: { url: payload.url || "./" },
    tag: payload.tag || "pans-plan-update"
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const requested = (event.notification.data && event.notification.data.url) || "./";
  event.waitUntil((async () => {
    let target;
    try { target = new URL(requested, self.location.origin); }
    catch (_) { target = new URL("./", self.location.origin); }
    if (target.origin !== self.location.origin) target = new URL("./", self.location.origin);
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const existing = windows.find(client => client.url.startsWith(self.location.origin));
    if (existing) {
      try { const navigated = await existing.navigate(target.href); return (navigated || existing).focus(); }
      catch (_) { return existing.focus(); }
    }
    return self.clients.openWindow(target.href);
  })());
});