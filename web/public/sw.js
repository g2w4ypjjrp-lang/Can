// Telefon bildirimleri (Web Push) için servis çalışanı; yalnızca /telefon kapsamında kayıtlıdır.
// Bildirim içeriği bilgisayardaki motorda bu tarayıcının anahtarına şifrelenir (RFC 8291);
// bildirim servisi (Apple/Google) içeriği okuyamaz, tarayıcı çözer ve burada gösterilir.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  const options = {
    body: data.body || "",
    icon: "/telefon-ikon-192.png",
    timestamp: typeof data.ts === "number" ? data.ts : Date.now(),
    data: { url: "/telefon" },
  };
  if (data.kind === "test") options.tag = "deneme";
  event.waitUntil(self.registration.showNotification(data.title || "AI Trading Intelligence", options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of windows) {
        if (new URL(client.url).pathname.startsWith("/telefon") && "focus" in client) {
          await client.focus();
          return;
        }
      }
      await self.clients.openWindow("/telefon");
    })(),
  );
});
