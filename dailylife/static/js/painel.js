/* Painel: próximo compromisso, to-do de hoje, lembretes e a semana. */
'use strict';

(() => {
  const { $, esc, get, post, patch, fail, toast, icon, parse } = DA;
  let semana = 0;
  let data = null;
  let selKey = null;

  const isUrl = (s) =>
    /^https?:\/\//i.test(s || '') || /meet\.google|zoom\.us|teams\.microsoft/i.test(s || '');
  const href = (s) => (/^https?:\/\//i.test(s) ? s : 'https://' + s);

  function hero(p) {
    const el = $('#p-proximo');
    if (!p) {
      el.className = 'hero empty-hero';
      el.innerHTML = `<div class="top"><span class="label">Próximo compromisso</span></div>
        <span class="title fs-18">Nada marcado nos próximos 7 dias</span>
        <button type="button" class="btn soft sm self-start" id="p-hero-add">+ Compromisso</button>`;
      $('#p-hero-add').onclick = () => DA.openEvento({});
      return;
    }
    el.className = 'hero';
    const link = isUrl(p.local)
      ? `<a class="go" href="${esc(href(p.local))}" target="_blank" rel="noopener">Entrar na chamada</a>`
      : `<button type="button" class="go" id="p-hero-open">Ver detalhes</button>`;
    const dia =
      p.inicio.slice(0, 10) === data.agora.slice(0, 10)
        ? ''
        : `${DA.DIAS[DA.weekday(parse(p.inicio))]}, ${parse(p.inicio).getDate()}/${DA.pad(parse(p.inicio).getMonth() + 1)} · `;
    el.innerHTML = `<div class="top"><span class="label">Próximo compromisso</span><span class="badge">${esc(p.em)}</span></div>
      <div class="stack gap-4">
        <span class="title">${esc(p.titulo)}</span>
        <span class="when">${dia}${esc(p.horario)}${p.local && !isUrl(p.local) ? ' · ' + esc(p.local) : ''}</span>
      </div>${link}`;
    const open = $('#p-hero-open');
    if (open) open.onclick = () => DA.openEvento({ id: p.id, ocorrencia: p.inicio });
  }

  function todos(list, prog) {
    $('#p-prog-txt').textContent = `${prog.feitos} de ${prog.total} feitas`;
    $('#p-prog-pct').textContent = `${prog.pct}%`;
    $('#p-prog-bar span').style.width = prog.pct + '%';
    $('#p-prog-bar').setAttribute('aria-valuenow', prog.pct);
    const box = $('#p-todos');
    if (!list.length) {
      box.innerHTML = '<p class="empty">Nenhuma tarefa para hoje. Aproveite!</p>';
      return;
    }
    box.innerHTML = list
      .map(
        (t) => `
      <div class="item${t.feito ? ' done' : ''}">
        <button type="button" class="check" data-todo="${t.id}" aria-pressed="${t.feito}" aria-label="Marcar: ${esc(t.titulo)}">${icon('check', 12)}</button>
        <button type="button" class="txt" data-open-todo="${t.id}">${esc(t.titulo)}</button>
        ${t.atrasada ? '<span class="tag late">atrasada</span>' : ''}
        ${t.subtarefas.length ? `<span class="tag">${t.subtarefas.filter((s) => s.feito).length}/${t.subtarefas.length}</span>` : ''}
        <span class="prio ${DA.prio(t.prioridade)}" title="Prioridade ${DA.prio(t.prioridade)}"></span>
      </div>`,
      )
      .join('');
  }

  function rems(list) {
    const box = $('#p-rems');
    $('#p-rem-h').textContent = `Lembretes · ${list.filter((r) => r.estado !== 'feito').length}`;
    if (!list.length) {
      box.innerHTML = '<p class="empty c-inherit op-70">Nada para lembrar hoje.</p>';
      return;
    }
    box.innerHTML = list
      .map((r) => {
        const done = r.estado === 'feito';
        return `<div class="item${done ? ' done' : ''}">
        <button type="button" class="check" data-rem="${r.id}" data-done="${done}" aria-pressed="${done}" aria-label="Marcar lembrete: ${esc(r.titulo)}">${icon('check', 12)}</button>
        <button type="button" class="txt fw-700" data-open-rem="${r.id}">${esc(r.titulo)}</button>
        <span class="tag${r.atrasado ? ' late' : ''}">${r.recorrente && done ? 'volta ' + esc(r.volta) : esc(r.hora)}</span>
      </div>`;
      })
      .join('');
  }

  function detail() {
    const box = $('#p-detail');
    const ev = data && data.semana.eventos.find((e) => `${e.id}|${e.inicio}` === selKey);
    if (!ev) {
      box.innerHTML = '';
      return;
    }
    const s = parse(ev.inicio);
    const when = ev.dia_inteiro ? 'Dia inteiro' : `${ev.inicio.slice(11, 16)} – ${ev.fim.slice(11, 16)}`;
    box.innerHTML = `<div class="detail">
      <div class="info"><span class="dot" style="--c:${esc(ev.cor)}"></span>
        <div class="stack min-w-0">
          <span class="t">${esc(ev.titulo)}</span>
          <span class="s">${DA.DIAS[DA.weekday(s)]}, ${s.getDate()}/${DA.pad(s.getMonth() + 1)} · ${when}${ev.local ? ' · ' + esc(ev.local) : ''} · ${esc(ev.calendario)}${ev.google ? ' (Google)' : ''}</span>
        </div></div>
      <div class="hrow">
        ${isUrl(ev.local) ? `<a class="btn ghost sm" href="${esc(href(ev.local))}" target="_blank" rel="noopener">Abrir link</a>` : ''}
        <button type="button" class="btn soft sm" id="p-edit">${ev.somente_leitura ? 'Ver' : 'Editar'}</button>
      </div></div>`;
    $('#p-edit').onclick = () => DA.openEvento({ id: ev.id, ocorrencia: ev.inicio });
  }

  function week(w) {
    $('#p-week-title').textContent = w.titulo;
    DA.timeline($('#p-timeline'), {
      days: w.dias,
      eventos: w.eventos,
      selKey,
      onPick: (ev) => {
        selKey = `${ev.id}|${ev.inicio}`;
        detail();
        week(data.semana);
      },
      onEmpty: (dia, hora) => DA.openEvento({ data: dia, hora }),
    });
    DA.legend($('#p-legend'), w.eventos);
  }

  async function load() {
    data = await get('/api/painel?semana=' + semana);
    $('#p-data').textContent = data.data_texto;
    $('#p-greeting').textContent = data.greeting;
    document.title = 'Daily Life';
    hero(data.proximo);
    todos(data.todos, data.progresso);
    rems(data.lembretes);
    if (selKey === null && data.proximo) selKey = `${data.proximo.id}|${data.proximo.inicio}`;
    detail();
    week(data.semana);
  }

  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-todo]');
    const r = e.target.closest('[data-rem]');
    const ot = e.target.closest('[data-open-todo]');
    const or = e.target.closest('[data-open-rem]');
    try {
      if (t) {
        await patch('/api/todos/' + t.dataset.todo, { feito: t.getAttribute('aria-pressed') !== 'true' });
        load();
      } else if (r) {
        await post(`/api/lembretes/${r.dataset.rem}/${r.dataset.done === 'true' ? 'desfazer' : 'resolver'}`);
        load();
      } else if (ot) DA.openTarefa({ id: ot.dataset.openTodo });
      else if (or) DA.openLembrete({ id: or.dataset.openRem });
    } catch (err) {
      fail(err);
    }
  });

  $('#p-quick').addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter' || !e.target.value.trim()) return;
    try {
      const t = await post('/api/todos', { texto: e.target.value, lista: 'hoje' });
      e.target.value = '';
      if (t.lista !== 'hoje' && !(t.vencimento && t.vencimento.slice(0, 10) <= DA.isoDate(DA.now()))) {
        toast('Tarefa adicionada', `Foi para a lista ${t.lista === 'semana' ? 'Semana' : 'Projetos'}.`);
      }
      load();
    } catch (err) {
      fail(err);
    }
  });

  $('#p-prev').onclick = () => {
    semana -= 1;
    selKey = '';
    load().catch(fail);
  };
  $('#p-next').onclick = () => {
    semana += 1;
    selKey = '';
    load().catch(fail);
  };
  $('#p-hoje').onclick = () => {
    semana = 0;
    selKey = null;
    load().catch(fail);
  };

  DA.onRefresh(load, { auto: true });
  load().catch(fail);
})();
