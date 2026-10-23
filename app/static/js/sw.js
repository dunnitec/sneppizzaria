// Service worker do app no celular (PWA): recebe os avisos (Web Push) e mostra uma página
// simples quando o celular está sem internet. Não guarda o cardápio em cache: preço e
// estoque sempre vêm atualizados do servidor.
const OFFLINE = `<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sem internet</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0b0b0c;color:#f5f5f4;font-family:Arial,sans-serif;text-align:center;padding:24px}
button{margin-top:16px;padding:12px 22px;border:0;border-radius:12px;background:#e3141b;color:#fff;font-weight:700;font-size:16px}</style></head>
<body><div><div style="font-size:48px">📶</div><h1 style="font-size:22px">Sem internet</h1><p>Confira a conexão do celular e tente de novo.</p>
<button onclick="location.reload()">Tentar de novo</button></div></body></html>`;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() =>
    new Response(OFFLINE, { headers: { "Content-Type": "text/html; charset=utf-8" } })));
});

self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (_) { d = { body: event.data ? event.data.text() : "" }; }
  event.waitUntil(self.registration.showNotification(d.title || "Pizzaria", {
    body: d.body || "", icon: d.icon, badge: d.badge, tag: d.tag || undefined, renotify: !!d.tag,
    data: { url: d.url || self.registration.scope },
  }));
});

// toque no aviso: abre (ou traz para a frente) o app na página do aviso
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.registration.scope).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) if (c.url === url && "focus" in c) return c.focus();
    for (const c of list) if ("navigate" in c) { c.focus(); return c.navigate(url); }
    return self.clients.openWindow(url);
  }));
});
