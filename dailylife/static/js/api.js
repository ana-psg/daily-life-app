/* Daily Life: utilidades compartilhadas por todas as telas. */
'use strict';

const DA = (() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
  const prio = (p) => (['alta', 'media', 'baixa'].includes(p) ? p : 'media');

  // Ícones do sprite em _icons.html (o mesmo que as telas usam)
  const icon = (name, size = 18) =>
    `<svg class="i" aria-hidden="true" width="${size}" height="${size}"><use href="#i-${name}"/></svg>`;

  // ---------- preferências deste aparelho (aba aberta, visão do calendário…) ----------
  const store = {
    get: (k) => {
      try {
        return localStorage.getItem('dailylife.' + k);
      } catch (_) {
        return null;
      }
    },
    set: (k, v) => {
      try {
        localStorage.setItem('dailylife.' + k, v);
      } catch (_) {
        /* navegador sem armazenamento */
      }
    },
  };

  // ---------- relógio: sempre o horário de São Paulo, venha de onde vier o aparelho ----------
  // O servidor manda a hora dele na página; guardamos a diferença para o relógio do aparelho.
  let clockOffset = 0;
  (() => {
    const raw = document.body && document.body.dataset.agora;
    if (!raw) return;
    const [dp, tp] = raw.split('T');
    const [y, m, d] = dp.split('-').map(Number);
    const [h, mi, s] = tp.split(':').map(Number);
    clockOffset = new Date(y, m - 1, d, h, mi, s || 0).getTime() - Date.now();
  })();
  const now = () => new Date(Date.now() + clockOffset);

  // ---------- datas ----------
  const DIAS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];
  const DIAS_LONGOS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
  const MESES = [
    'janeiro',
    'fevereiro',
    'março',
    'abril',
    'maio',
    'junho',
    'julho',
    'agosto',
    'setembro',
    'outubro',
    'novembro',
    'dezembro',
  ];
  const pad = (n) => String(n).padStart(2, '0');
  const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const isoDT = (d) => `${isoDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const parse = (s) => {
    const [dp, tp = '00:00'] = String(s).split('T');
    const [y, m, d] = dp.split('-').map(Number);
    const [h, mi] = tp.split(':').map(Number);
    return new Date(y, m - 1, d, h || 0, mi || 0);
  };
  const addDays = (d, n) => {
    const x = new Date(d);
    x.setDate(x.getDate() + n);
    return x;
  };
  const weekday = (d) => (d.getDay() + 6) % 7; // 0 = segunda
  const startOfWeek = (d) => {
    const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    return addDays(x, -weekday(x));
  };
  const hm = (s) => String(s).slice(11, 16);
  const longDate = (d) => `${DIAS_LONGOS[weekday(d)]}, ${d.getDate()} de ${MESES[d.getMonth()]}`;

  // ---------- API ----------
  async function api(method, url, data) {
    const opts = { method, headers: {} };
    if (data instanceof FormData) opts.body = data;
    else if (data !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(data);
    }
    const res = await fetch(url, opts);
    if (res.status === 401) {
      location.href = '/entrar?proximo=' + encodeURIComponent(location.pathname);
      throw new Error('PIN');
    }
    let json = {};
    try {
      json = await res.json();
    } catch (_) {
      /* sem corpo */
    }
    if (!res.ok) throw new Error(json.erro || `Erro ${res.status}`);
    return json;
  }
  const get = (u) => api('GET', u);
  const post = (u, d = {}) => api('POST', u, d);
  const patch = (u, d) => api('PATCH', u, d);
  const del = (u) => api('DELETE', u);

  // ---------- avisos na tela ----------
  function toast(title, body = '', kind = '') {
    const box = $('#toasts');
    if (!box) return;
    const el = document.createElement('div');
    el.className = 'toast' + (kind === 'err' ? ' err' : '');
    el.setAttribute('role', kind === 'err' ? 'alert' : 'status');
    el.innerHTML = `<div><div class="tt">${esc(title)}</div>${body ? `<div class="tb">${esc(body)}</div>` : ''}</div>
      <button class="x" type="button" aria-label="Fechar aviso">${icon('x', 14)}</button>`;
    el.querySelector('.x').onclick = () => el.remove();
    box.appendChild(el);
    setTimeout(() => el.remove(), kind === 'err' ? 7000 : 6000);
  }
  const fail = (e) => {
    if (e && e.message !== 'PIN') toast('Não deu certo', e.message, 'err');
  };

  // ---------- tema ----------
  function applyTheme(tema) {
    const root = document.documentElement;
    root.dataset.tema = tema;
    let t = tema;
    if (t === 'sistema') t = matchMedia('(prefers-color-scheme: dark)').matches ? 'escuro' : 'claro';
    root.dataset.theme = t === 'escuro' ? 'escuro' : 'claro';
    const dark = root.dataset.theme === 'escuro';
    $$('.when-light').forEach((e) => (e.hidden = dark));
    $$('.when-dark').forEach((e) => (e.hidden = !dark));
  }
  async function toggleTheme() {
    const next = document.documentElement.dataset.theme === 'escuro' ? 'claro' : 'escuro';
    applyTheme(next);
    try {
      await patch('/api/config', { tema: next });
    } catch (e) {
      fail(e);
    }
  }
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if (document.documentElement.dataset.tema === 'sistema') applyTheme('sistema');
  });

  // ---------- app de computador (pywebview) ----------
  const isLocal = document.body.dataset.local === '1';
  let isDesktop = !!window.pywebview;
  async function windowAction(acao) {
    try {
      await post('/api/janela/' + acao);
    } catch (e) {
      if (acao === 'widget') location.href = '/widget';
      else if (acao === 'painel') location.href = '/';
    }
  }
  function markDesktop() {
    isDesktop = true;
    $$('#btn-widget, #w-esconder').forEach((b) => (b.hidden = false));
  }
  window.addEventListener('pywebviewready', markDesktop);

  // ---------- atualização das telas ----------
  // Cada tela registra a função que recarrega seus dados. auto = recarregar também a cada minuto
  // (painel e widget mostram horários e atrasos que mudam com o tempo).
  let refreshFn = () => {};
  let autoRefresh = false;
  const onRefresh = (fn, { auto = false } = {}) => {
    refreshFn = fn;
    autoRefresh = auto;
  };
  const refresh = () => Promise.resolve(refreshFn()).catch(fail);

  // ---------- estado: uma consulta só para avisos e status do Google ----------
  const POLL_MS = 20000;
  let lastNote = null;
  let lastSession = null;
  let ticks = 0;

  function showGoogle(g) {
    const pill = $('#sync-pill');
    if (!pill) return;
    pill.hidden = !g.conectado;
    if (!g.conectado) return;
    pill.querySelector('.dot').className = 'dot ' + (g.erro ? 'warn' : 'ok');
    pill.querySelector('.txt').textContent = g.sincronizando
      ? 'Sincronizando…'
      : g.erro
        ? 'Google: ver Configurações'
        : 'Google sincronizado';
    pill.title = g.erro || (g.ultima_sync ? 'Última sincronização: ' + hm(g.ultima_sync) : '');
  }

  async function pollState() {
    let changed = false;
    try {
      let r = await get('/api/estado' + (lastNote === null ? '' : '?desde=' + lastNote));
      // O app foi reaberto e a contagem recomeçou: pega tudo desde a reabertura
      if (lastSession && r.sessao !== lastSession) r = await get('/api/estado?desde=0');
      if (lastNote !== null && r.itens.length) {
        r.itens.forEach((n) => toast(n.titulo, n.corpo));
        changed = true;
      }
      lastNote = r.ultimo;
      lastSession = r.sessao;
      showGoogle(r.google);
    } catch (_) {
      /* sem conexão: tenta de novo na próxima */
    }
    ticks += 1;
    if (autoRefresh && ticks % 3 === 0) changed = true;
    if (changed && !document.querySelector('dialog[open]')) refresh();
  }

  // ---------- menu "Novo" e atalhos ----------
  function openNew(tipo) {
    if (tipo === 'tarefa') DA.openTarefa({});
    if (tipo === 'compromisso') DA.openEvento({});
    if (tipo === 'lembrete') DA.openLembrete({});
  }
  function setupNewMenu() {
    const btn = $('#btn-novo');
    const menu = $('#new-menu');
    if (!btn || !menu) return;
    const close = () => {
      menu.hidden = true;
      btn.setAttribute('aria-expanded', 'false');
    };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const r = btn.getBoundingClientRect();
      menu.hidden = !menu.hidden;
      btn.setAttribute('aria-expanded', String(!menu.hidden));
      if (!menu.hidden) {
        const up = r.top > window.innerHeight / 2;
        menu.style.left = Math.max(8, Math.min(r.right - 200, window.innerWidth - 208)) + 'px';
        menu.style.top = up ? '' : r.bottom + window.scrollY + 'px';
        menu.style.bottom = up ? window.innerHeight - r.top + 8 + 'px' : '';
        menu.style.position = up ? 'fixed' : 'absolute';
        menu.querySelector('button').focus();
      }
    });
    menu.addEventListener('click', (e) => {
      const b = e.target.closest('[data-novo]');
      if (b) {
        close();
        openNew(b.dataset.novo);
      }
    });
    document.addEventListener('click', (e) => {
      if (!menu.contains(e.target)) close();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') close();
    });
  }
  function setupShortcuts() {
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const tag = (e.target.tagName || '').toLowerCase();
      if (['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable) return;
      if (document.querySelector('dialog[open]')) return;
      const k = e.key.toLowerCase();
      const page = document.body.dataset.page;
      const go = { 1: '/', 2: '/calendario', 3: '/todo', 4: '/lembretes' };
      if (k === 'n') {
        e.preventDefault();
        const q = $('#p-quick, #t-quick, #w-quick');
        q ? q.focus() : openNew('tarefa');
      } else if (k === 'c') {
        e.preventDefault();
        openNew('compromisso');
      } else if (k === 'l') {
        e.preventDefault();
        openNew('lembrete');
      } else if (k === 't') {
        e.preventDefault();
        toggleTheme();
      } else if (k === 'w' && isDesktop) {
        e.preventDefault();
        windowAction(page === 'widget' ? 'painel' : 'widget');
      } else if (go[k] && page !== 'widget') {
        e.preventDefault();
        location.href = go[k];
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(document.documentElement.dataset.tema);
    if (window.pywebview) markDesktop();
    $('#btn-tema')?.addEventListener('click', toggleTheme);
    $('#btn-widget')?.addEventListener('click', () => windowAction('widget'));
    setupNewMenu();
    setupShortcuts();
    pollState();
    setInterval(pollState, POLL_MS);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refresh();
    });
    if ('serviceWorker' in navigator && window.isSecureContext && !window.pywebview) {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
  });

  return {
    $,
    $$,
    esc,
    prio,
    icon,
    store,
    api,
    get,
    post,
    patch,
    del,
    toast,
    fail,
    applyTheme,
    windowAction,
    onRefresh,
    refresh,
    pollState,
    openNew,
    now,
    DIAS,
    DIAS_LONGOS,
    MESES,
    pad,
    isoDate,
    isoDT,
    parse,
    addDays,
    weekday,
    startOfWeek,
    hm,
    longDate,
    get isDesktop() {
      return isDesktop;
    },
    isLocal,
  };
})();
