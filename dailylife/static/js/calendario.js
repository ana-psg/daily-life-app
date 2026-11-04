/* Calendário: visões Mês, Semana e Dia, dia selecionado e calendários visíveis. */
'use strict';

(() => {
  const {
    $,
    $$,
    esc,
    get,
    patch,
    fail,
    isoDate,
    isoDT,
    parse,
    addDays,
    startOfWeek,
    weekday,
    DIAS,
    MESES,
    store,
  } = DA;

  let view = store.get('view') || 'mes';
  let cursor = DA.now();
  let selDay = isoDate(DA.now());
  let eventos = [];
  let selKey = null;

  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  function range() {
    if (view === 'mes') {
      const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
      const start = startOfWeek(first);
      const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
      const end = addDays(startOfWeek(last), 7);
      return [start, end];
    }
    if (view === 'semana') {
      const s = startOfWeek(cursor);
      return [s, addDays(s, 7)];
    }
    const s = new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate());
    return [s, addDays(s, 1)];
  }

  function eventsOn(dayIso) {
    const d0 = parse(dayIso);
    const d1 = addDays(d0, 1);
    return eventos.filter((e) => parse(e.inicio) < d1 && parse(e.fim) > d0);
  }

  function titles() {
    $('#c-ano').textContent = cursor.getFullYear();
    if (view === 'mes') $('#c-titulo').textContent = cap(MESES[cursor.getMonth()]);
    else if (view === 'semana') {
      const s = startOfWeek(cursor);
      const e = addDays(s, 6);
      $('#c-titulo').textContent =
        s.getMonth() === e.getMonth()
          ? `${s.getDate()} – ${e.getDate()} de ${MESES[s.getMonth()]}`
          : `${s.getDate()} ${MESES[s.getMonth()].slice(0, 3)} – ${e.getDate()} ${MESES[e.getMonth()].slice(0, 3)}`;
    } else $('#c-titulo').textContent = DA.longDate(cursor);
    $$('#c-views button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
  }

  function renderMonth(start, end) {
    const today = isoDate(DA.now());
    let html =
      '<div class="tl-scroll"><div class="month-wrap"><div class="month-head">' +
      DIAS.map((d) => `<span>${d}</span>`).join('') +
      '</div><div class="month">';
    for (let d = new Date(start); d < end; d = addDays(d, 1)) {
      const iso = isoDate(d);
      const list = eventsOn(iso);
      const out = d.getMonth() !== cursor.getMonth();
      const cls = ['mcell', out ? 'out' : '', iso === today ? 'today' : '', iso === selDay ? 'sel' : ''].join(
        ' ',
      );
      html += `<button type="button" class="${cls}" data-day="${iso}" aria-label="${d.getDate()} de ${MESES[d.getMonth()]}, ${list.length} compromissos">
        <span class="num">${d.getDate()}</span>
        ${list
          .slice(0, 3)
          .map(
            (e) =>
              `<span class="ev chip-ev" style="--c:${esc(e.cor)}">${e.dia_inteiro ? '' : e.inicio.slice(11, 16) + ' '}${esc(e.titulo)}</span>`,
          )
          .join('')}
        ${list.length > 3 ? `<span class="more">+${list.length - 3}</span>` : ''}
      </button>`;
    }
    html += '</div></div></div>';
    $('#c-main').innerHTML = html;
    $$('#c-main [data-day]').forEach((b) => {
      b.addEventListener('click', () => {
        selDay = b.dataset.day;
        renderMonth(start, end);
        sidebar();
      });
      b.addEventListener('dblclick', () => DA.openEvento({ data: b.dataset.day }));
    });
  }

  function renderTimeline(start, end) {
    const today = isoDate(DA.now());
    const days = [];
    for (let d = new Date(start); d < end; d = addDays(d, 1)) {
      days.push({ data: isoDate(d), nome: DIAS[weekday(d)], num: d.getDate(), hoje: isoDate(d) === today });
    }
    $('#c-main').innerHTML = '<div id="c-tl"></div><div class="legend mt-12" id="c-legend"></div>';
    DA.timeline($('#c-tl'), {
      days,
      eventos,
      selKey,
      onPick: (ev) => {
        selKey = `${ev.id}|${ev.inicio}`;
        DA.openEvento({ id: ev.id, ocorrencia: ev.inicio });
      },
      onEmpty: (dia, hora) => DA.openEvento({ data: dia, hora }),
    });
    DA.legend($('#c-legend'), eventos);
  }

  function sidebar() {
    const d = parse(selDay);
    $('#c-dia-h').textContent = DA.longDate(d);
    const list = eventsOn(selDay);
    $('#c-dia-lista').innerHTML = list.length
      ? list
          .map(
            (e) => `
      <button type="button" class="ev day-ev" style="--c:${esc(e.cor)}" data-ev="${e.id}" data-oc="${e.inicio}">
        <span class="h">${e.dia_inteiro ? 'Dia inteiro' : `${e.inicio.slice(11, 16)} – ${e.fim.slice(11, 16)}`}${e.local ? ' · ' + esc(e.local) : ''}</span>
        <span class="t">${esc(e.titulo)}</span>
      </button>`,
          )
          .join('')
      : '<p class="empty">Dia livre.</p>';
    $$('#c-dia-lista [data-ev]').forEach((b) =>
      b.addEventListener('click', () => DA.openEvento({ id: b.dataset.ev, ocorrencia: b.dataset.oc })),
    );
  }

  async function calendars() {
    const r = await get('/api/calendarios');
    $('#c-cals').innerHTML = r.itens
      .map(
        (c) => `
      <button type="button" class="cal-toggle" aria-pressed="${c.visivel}" data-cal="${c.id}" style="--c:${esc(c.cor)}">
        <span class="box"></span><span class="nm">${esc(c.nome)}</span><span class="src">${c.origem === 'google' ? 'Google' : 'Local'}</span>
      </button>`,
      )
      .join('');
  }

  async function load() {
    const [start, end] = range();
    titles();
    const r = await get(`/api/eventos?inicio=${isoDT(start)}&fim=${isoDT(end)}`);
    eventos = r.itens;
    if (view === 'mes') renderMonth(start, end);
    else renderTimeline(start, end);
    if (view === 'dia') selDay = isoDate(cursor);
    sidebar();
  }

  function move(dir) {
    if (view === 'mes') {
      const day = parse(selDay).getDate();
      cursor = new Date(cursor.getFullYear(), cursor.getMonth() + dir, 1);
      const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate();
      selDay = isoDate(new Date(cursor.getFullYear(), cursor.getMonth(), Math.min(day, last)));
    } else cursor = addDays(cursor, view === 'semana' ? 7 * dir : dir);
    if (view !== 'mes') selDay = isoDate(cursor);
    load().catch(fail);
  }

  $('#c-prev').onclick = () => move(-1);
  $('#c-next').onclick = () => move(1);
  $('#c-hoje').onclick = () => {
    cursor = DA.now();
    selDay = isoDate(cursor);
    load().catch(fail);
  };
  $('#c-views').addEventListener('click', (e) => {
    const b = e.target.closest('[data-view]');
    if (!b) return;
    view = b.dataset.view;
    store.set('view', view);
    if (view !== 'mes') cursor = parse(selDay);
    load().catch(fail);
  });
  $('#c-add-dia').onclick = () => DA.openEvento({ data: selDay });
  $('#c-cals').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-cal]');
    if (!b) return;
    try {
      await patch('/api/calendarios/' + b.dataset.cal, {
        visivel: b.getAttribute('aria-pressed') !== 'true',
      });
      await calendars();
      await load();
    } catch (err) {
      fail(err);
    }
  });

  DA.onRefresh(() => Promise.all([calendars(), load()]));
  Promise.all([calendars(), load()]).catch(fail);
})();
