/* Widget compacto: hora, próximo compromisso, o resto do dia, to-do e lembretes. */
'use strict';

(() => {
  const { $, esc, get, post, patch, fail, icon, parse } = DA;
  const isUrl = (s) =>
    /^https?:\/\//i.test(s || '') || /meet\.google|zoom\.us|teams\.microsoft/i.test(s || '');

  function clock() {
    const d = DA.now();
    $('#w-hora').textContent = `${DA.pad(d.getHours())}:${DA.pad(d.getMinutes())}`;
  }

  async function load() {
    const data = await get('/api/painel');
    $('#w-data').textContent = data.data_curta;
    clock();

    const p = data.proximo;
    $('#w-proximo').innerHTML = p
      ? `
      <div class="whero">
        <div class="top"><span>${esc(p.horario)}${p.inicio.slice(0, 10) !== data.agora.slice(0, 10) ? ' · ' + DA.DIAS[DA.weekday(parse(p.inicio))] : ''}</span><span class="badge">${esc(p.em)}</span></div>
        <button type="button" class="title" style="background:none;border:none;color:inherit;text-align:left;padding:0" data-ev="${p.id}" data-oc="${p.inicio}">${esc(p.titulo)}</button>
        ${isUrl(p.local) ? `<a href="${esc(/^https?:/.test(p.local) ? p.local : 'https://' + p.local)}" target="_blank" rel="noopener">Entrar na chamada</a>` : p.local ? `<span style="font-size:12px;font-weight:700;opacity:.85">${esc(p.local)}</span>` : ''}
      </div>`
      : `<div class="wcard"><span class="muted" style="font-size:13px;font-weight:700">Nada marcado nos próximos dias</span></div>`;

    const now = data.agora;
    const later = data.hoje_eventos.filter(
      (e) => !e.dia_inteiro && e.fim > now && (!p || `${e.id}|${e.inicio}` !== `${p.id}|${p.inicio}`),
    );
    $('#w-depois-box').hidden = !later.length;
    $('#w-depois').innerHTML = later
      .slice(0, 4)
      .map(
        (e) => `
      <button type="button" class="wline" style="background:none;border:none;width:100%;text-align:left;padding:0" data-ev="${e.id}" data-oc="${e.inicio}">
        <span class="dot" style="--c:${esc(e.cor)}"></span><b>${e.inicio.slice(11, 16)}</b><span>${esc(e.titulo)}</span></button>`,
      )
      .join('');

    const pend = data.todos.filter((t) => !t.feito);
    const feitos = data.todos.filter((t) => t.feito);
    $('#w-prog').textContent = `${feitos.length}/${data.todos.length}`;
    const shown = pend.slice(0, 5).concat(pend.length < 5 ? feitos.slice(0, 5 - pend.length) : []);
    $('#w-todos').innerHTML = shown.length
      ? shown
          .map(
            (t) => `
      <div class="item${t.feito ? ' done' : ''}" style="min-height:38px">
        <button type="button" class="check" style="width:20px;height:20px" data-todo="${t.id}" aria-pressed="${t.feito}" aria-label="Marcar: ${esc(t.titulo)}">${icon('check', 10)}</button>
        <span class="txt" style="font-size:13px">${esc(t.titulo)}</span>
      </div>`,
          )
          .join('')
      : '<p class="empty">Tudo feito por hoje.</p>';

    const rems = data.lembretes.filter((r) => r.estado !== 'feito');
    $('#w-rems-box').hidden = !rems.length;
    $('#w-rems').innerHTML = rems
      .slice(0, 4)
      .map(
        (r) => `
      <div class="wl${r.atrasado ? ' late' : ''}">
        <button type="button" class="check" style="width:18px;height:18px;border-color:var(--sticky-ink)" data-rem="${r.id}" aria-label="Marcar lembrete: ${esc(r.titulo)}">${icon('check', 10)}</button>
        <span style="flex:1;font-weight:700">${esc(r.titulo)}</span><b>${esc(r.hora)}</b></div>`,
      )
      .join('');
  }

  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-todo]');
    const r = e.target.closest('[data-rem]');
    const ev = e.target.closest('[data-ev]');
    try {
      if (t) {
        await patch('/api/todos/' + t.dataset.todo, { feito: t.getAttribute('aria-pressed') !== 'true' });
        load();
      } else if (r) {
        await post(`/api/lembretes/${r.dataset.rem}/resolver`);
        load();
      } else if (ev) DA.openEvento({ id: ev.dataset.ev, ocorrencia: ev.dataset.oc });
    } catch (err) {
      fail(err);
    }
  });

  $('#w-quick').addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter' || !e.target.value.trim()) return;
    try {
      await post('/api/todos', { texto: e.target.value, lista: 'hoje' });
      e.target.value = '';
      load();
    } catch (err) {
      fail(err);
    }
  });

  // No app de computador, links do widget abrem a tela no painel (janela grande)
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="/"]');
    if (!a || !DA.isDesktop) return;
    e.preventDefault();
    post('/api/janela/abrir', { url: a.getAttribute('href') }).catch(fail);
  });
  $('#w-esconder').addEventListener('click', () => DA.windowAction('esconder'));

  DA.onRefresh(load, { auto: true });
  load().catch(fail);
  setInterval(clock, 10000);
})();
