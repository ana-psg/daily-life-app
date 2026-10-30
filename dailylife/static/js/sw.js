/* Service worker: deixa instalar o Daily Life como app no celular e mostra os avisos do PC
   (Web Push). Não guarda dados offline; tudo vem do PC pelo Tailscale. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => {
  /* passa direto para a rede */
});

self.addEventListener('push', (e) => {
  let d = {};
  try {
    d = e.data ? e.data.json() : {};
  } catch (_) {
    d = { corpo: e.data ? e.data.text() : '' };
  }
  const isReminder = d.tipo === 'lembrete' && d.id;
  e.waitUntil(
    self.registration.showNotification(d.titulo || 'Daily Life', {
      body: d.corpo || '',
      icon: '/static/img/icon-192.png',
      tag: d.tipo && d.id ? `${d.tipo}-${d.id}` : undefined,
      silent: !!d.silencioso,
      data: d,
      actions: isReminder
        ? [
            { action: 'resolver', title: 'Resolvido' },
            { action: 'adiar', title: 'Adiar 1 h' },
          ]
        : [],
    }),
  );
});

function openApp(url) {
  return self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
    const win = list.find((c) => 'focus' in c);
    if (win) {
      win.navigate(url).catch(() => {});
      return win.focus();
    }
    return self.clients.openWindow(url);
  });
}

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const d = e.notification.data || {};
  if ((e.action === 'resolver' || e.action === 'adiar') && d.id) {
    // Marca direto, sem abrir o app; se a sessão expirou, abre para entrar com a senha
    const body = e.action === 'adiar' ? { minutos: 60 } : {};
    e.waitUntil(
      fetch(`/api/lembretes/${d.id}/${e.action}`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
        .then((r) => (r.ok ? null : openApp(d.url || '/lembretes')))
        .catch(() => openApp(d.url || '/lembretes')),
    );
    return;
  }
  e.waitUntil(openApp(d.url || '/'));
});
