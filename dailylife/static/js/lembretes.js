/* Lembretes: filtros, cartões, resolver, adiar. */
'use strict';

(() => {
  const { $, $$, esc, get, post, fail, toast, icon } = DA;
  const CORES = { amarelo: '#F2B33D', rosa: '#E85A93', azul: '#5B7FFF', verde: '#36B072', lilas: '#7152F0' };
  let filtro = 'todos';

  function card(r) {
    const done = r.estado === 'feito';
    const tag = r.atrasado ? 'Atrasado' : r.repeticao_texto || 'Uma vez';
    const when =
      done && r.recorrente
        ? `Feito hoje · volta ${esc(r.volta)} às ${esc(r.hora)}`
        : done
          ? 'Resolvido'
          : esc(r.when_text);
    return `<article class="rem${done ? ' done' : ''}" style="--c:${CORES[r.cor] || CORES.amarelo}">
      <div class="top">
        <span class="ic">${icon('bell', 18)}</span>
        <span class="tag${r.atrasado ? ' late' : ''}">${esc(tag)}</span>
      </div>
      <button type="button" class="main" data-open="${r.id}">
        <h2>${esc(r.titulo)}</h2>
        ${r.descricao ? `<p>${esc(r.descricao)}</p>` : ''}
      </button>
      <div class="foot">
        <span class="when${r.atrasado ? ' late' : ''}">${when}</span>
        <div class="acts">
          ${done ? '' : `<button type="button" class="round plain" data-snooze="${r.id}" aria-label="Adiar 1 hora: ${esc(r.titulo)}" title="Adiar 1 h">${icon('clock', 15)}</button>`}
          <button type="button" class="round${done ? ' on' : ''}" data-done="${r.id}" data-state="${done}" aria-pressed="${done}"
            aria-label="${done ? 'Desfazer' : 'Marcar como feito'}: ${esc(r.titulo)}" title="${done ? 'Desfazer' : 'Feito'}">${icon('check', 15)}</button>
        </div>
      </div>
    </article>`;
  }

  async function load() {
    const r = await get('/api/lembretes?filtro=' + filtro);
    $$('#l-filtros [data-f]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.f === filtro)));
    const abertos = r.itens.filter((x) => x.estado !== 'feito').length;
    $('#l-sub').textContent =
      filtro === 'resolvidos' ? `${r.itens.length} resolvidos` : `${abertos} em aberto`;
    $('#l-grid').innerHTML = r.itens.length
      ? r.itens.map(card).join('')
      : '<p class="empty" style="grid-column:1/-1;text-align:center;padding:24px">Nenhum lembrete aqui.</p>';
  }

  $('#l-filtros').addEventListener('click', (e) => {
    const b = e.target.closest('[data-f]');
    if (!b) return;
    filtro = b.dataset.f;
    load().catch(fail);
  });
  $('#l-grid').addEventListener('click', async (e) => {
    const d = e.target.closest('[data-done]');
    const s = e.target.closest('[data-snooze]');
    const o = e.target.closest('[data-open]');
    try {
      if (d) {
        const r = await post(
          `/api/lembretes/${d.dataset.done}/${d.dataset.state === 'true' ? 'desfazer' : 'resolver'}`,
        );
        if (r.recorrente && r.feito_hoje) toast('Feito por hoje', `Volta ${r.volta} às ${r.hora}.`);
        load();
      } else if (s) {
        await post(`/api/lembretes/${s.dataset.snooze}/adiar`, { minutos: 60 });
        toast('Adiado por 1 hora');
        load();
      } else if (o) DA.openLembrete({ id: o.dataset.open });
    } catch (err) {
      fail(err);
    }
  });
  $('#l-novo').addEventListener('click', () => DA.openLembrete({}));

  DA.onRefresh(load);
  load().catch(fail);
})();
