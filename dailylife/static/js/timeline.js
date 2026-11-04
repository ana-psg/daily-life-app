/* Linha do tempo por horário (usada na semana do painel e nas visões Dia/Semana). */
'use strict';

(() => {
  // Altura de uma hora: vem do token --hour do CSS (tokens.css), para os dois nunca ficarem diferentes
  const HOUR = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--hour')) || 44;
  const { esc, parse, isoDate, addDays, pad } = DA;

  // Distribui eventos que se sobrepõem em colunas lado a lado
  function layout(items) {
    items.sort((a, b) => a.s - b.s || b.e - a.e);
    const out = [];
    let cluster = [];
    let clusterEnd = -1;
    const flush = () => {
      const cols = [];
      cluster.forEach((it) => {
        let c = cols.findIndex((end) => end <= it.s);
        if (c === -1) {
          c = cols.length;
          cols.push(it.e);
        } else cols[c] = it.e;
        it.col = c;
      });
      cluster.forEach((it) => {
        it.ncol = cols.length;
        out.push(it);
      });
      cluster = [];
    };
    items.forEach((it) => {
      if (cluster.length && it.s >= clusterEnd) flush();
      cluster.push(it);
      clusterEnd = Math.max(clusterEnd, it.e);
    });
    if (cluster.length) flush();
    return out;
  }

  /**
   * opts: { days: [{data:'YYYY-MM-DD', nome, num, hoje}], eventos, selKey, onPick(ev), onEmpty(dataISO, hora) }
   */
  function render(container, opts) {
    const days = opts.days;
    const n = days.length;
    const prevScroll = container.querySelector('.tl-vscroll')?.scrollTop;
    const byDay = days.map(() => ({ allday: [], timed: [] }));
    const index = new Map(days.map((d, i) => [d.data, i]));

    opts.eventos.forEach((ev, k) => {
      const s = parse(ev.inicio);
      const e = parse(ev.fim);
      const key = `${ev.id}|${ev.inicio}`;
      if (ev.dia_inteiro) {
        for (let d = new Date(s.getFullYear(), s.getMonth(), s.getDate()); d < e; d = addDays(d, 1)) {
          const i = index.get(isoDate(d));
          if (i !== undefined) byDay[i].allday.push({ ev, key, k });
        }
        return;
      }
      for (let d = new Date(s.getFullYear(), s.getMonth(), s.getDate()); d < e; d = addDays(d, 1)) {
        const i = index.get(isoDate(d));
        if (i === undefined) continue;
        const dayStart = d.getTime();
        const st = Math.max(s.getTime(), dayStart);
        const en = Math.min(e.getTime(), dayStart + 864e5);
        byDay[i].timed.push({ ev, key, k, s: (st - dayStart) / 36e5, e: (en - dayStart) / 36e5 });
      }
    });

    const hasAllday = byDay.some((d) => d.allday.length);
    const now = DA.now();
    const nowH = now.getHours() + now.getMinutes() / 60;

    let html = `<div class="tl-scroll"><div class="tl${n === 1 ? ' one-day' : ''}" style="--n:${n}">`;
    html +=
      '<div class="tl-days"><div></div>' +
      days
        .map(
          (d) =>
            `<div class="tl-day${d.hoje ? ' today' : ''}"><span class="n">${esc(d.nome)}</span><span class="d">${d.num}</span></div>`,
        )
        .join('') +
      '</div>';
    if (hasAllday) {
      html +=
        '<div class="tl-allday"><div class="muted fs-11 fw-600">dia todo</div>' +
        byDay
          .map(
            (d) =>
              `<div class="cell">${d.allday.map((a) => `<button type="button" class="ev chip-ev${a.key === opts.selKey ? ' sel' : ''}" style="--c:${esc(a.ev.cor)}" data-k="${a.k}">${esc(a.ev.titulo)}</button>`).join('')}</div>`,
          )
          .join('') +
        '</div>';
    }
    html += '<div class="tl-vscroll"><div class="tl-body"><div class="tl-hours">';
    for (let h = 0; h < 24; h++) html += `<span>${h ? pad(h) + ':00' : ''}</span>`;
    html += '</div>';
    days.forEach((d, i) => {
      html += `<div class="tl-col${d.hoje ? ' today' : ''}" data-date="${d.data}" role="group" aria-label="${esc(d.nome)} ${d.num}">`;
      layout(byDay[i].timed).forEach((it) => {
        const top = it.s * HOUR + 2;
        const height = Math.max(20, (it.e - it.s) * HOUR - 4);
        const w = 100 / it.ncol;
        const long = height >= 36;
        html += `<button type="button" class="ev${it.key === opts.selKey ? ' sel' : ''}" data-k="${it.k}"
          style="--c:${esc(it.ev.cor)};top:${top}px;height:${height}px;left:calc(${it.col * w}% + 3px);width:calc(${w}% - 6px)"
          title="${esc(it.ev.titulo)} · ${it.ev.inicio.slice(11, 16)}–${it.ev.fim.slice(11, 16)}">
          <span class="t">${esc(it.ev.titulo)}</span>${long ? `<span class="h">${it.ev.inicio.slice(11, 16)} – ${it.ev.fim.slice(11, 16)}</span>` : ''}</button>`;
      });
      if (d.hoje) html += `<div class="now-line" style="top:${nowH * HOUR}px"></div>`;
      html += '</div>';
    });
    html += '</div></div></div></div>';
    container.innerHTML = html;

    const vs = container.querySelector('.tl-vscroll');
    vs.scrollTop =
      prevScroll ?? Math.max(0, (days.some((d) => d.hoje) ? Math.min(nowH - 1.5, 15) : 7.5) * HOUR);

    container.querySelectorAll('[data-k]').forEach((b) =>
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        opts.onPick && opts.onPick(opts.eventos[Number(b.dataset.k)]);
      }),
    );
    container.querySelectorAll('.tl-col').forEach((col) =>
      col.addEventListener('dblclick', (e) => {
        if (e.target !== col || !opts.onEmpty) return;
        const y = e.offsetY;
        const h = Math.max(0, Math.min(23, Math.floor(y / HOUR)));
        opts.onEmpty(col.dataset.date, `${pad(h)}:00`);
      }),
    );
  }

  function legend(el, eventos) {
    const seen = new Map();
    eventos.forEach((e) => seen.set(e.calendario, e.cor));
    el.innerHTML = Array.from(seen)
      .map(([nome, cor]) => `<span><span class="dot" style="--c:${esc(cor)}"></span>${esc(nome)}</span>`)
      .join('');
  }

  DA.timeline = render;
  DA.legend = legend;
})();
