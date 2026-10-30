/* To-do: abas, tarefas com subtarefas, prioridade, arrastar para reordenar. */
'use strict';

(() => {
  const { $, $$, esc, get, post, patch, fail, toast, icon, parse, DIAS, MESES, store } = DA;
  let aba = store.get('aba') || 'hoje';
  let itens = [];
  const LISTAS = { hoje: 'Hoje', semana: 'Semana', projetos: 'Projetos' };

  function meta(t) {
    const parts = [LISTAS[t.lista] || ''];
    if (t.vencimento) {
      const d = parse(t.vencimento);
      const hoje = DA.isoDate(DA.now());
      const amanha = DA.isoDate(DA.addDays(DA.now(), 1));
      const v = t.vencimento.slice(0, 10);
      parts.push(
        v === hoje
          ? 'hoje'
          : v === amanha
            ? 'amanhã'
            : `${DIAS[DA.weekday(d)].toLowerCase()}, ${d.getDate()} ${MESES[d.getMonth()].slice(0, 3)}`,
      );
    }
    if (t.subtarefas.length)
      parts.push(`${t.subtarefas.filter((s) => s.feito).length} de ${t.subtarefas.length} etapas`);
    if (t.feito && aba === 'feitas' && t.feito_em)
      parts.push('feita em ' + t.feito_em.slice(8, 10) + '/' + t.feito_em.slice(5, 7));
    return parts.filter(Boolean).join(' · ');
  }

  function render(contagem) {
    $$('#t-tabs [data-aba]').forEach((b) => {
      const on = b.dataset.aba === aba;
      b.setAttribute('aria-selected', String(on));
      const n = contagem[b.dataset.aba];
      b.textContent = `${{ hoje: 'Hoje', semana: 'Semana', projetos: 'Projetos', feitas: 'Feitas' }[b.dataset.aba]} · ${n}`;
    });
    const box = $('#t-list');
    if (!itens.length) {
      box.innerHTML = `<p class="empty" style="text-align:center;padding:24px">${aba === 'feitas' ? 'Nenhuma tarefa concluída ainda.' : 'Nada por aqui. Adicione uma tarefa acima.'}</p>`;
      return;
    }
    box.innerHTML = itens
      .map(
        (t) => `
      <div class="todo-card${t.feito ? ' done' : ''}" data-id="${t.id}" draggable="${aba !== 'feitas'}">
        <div class="row1">
          <button type="button" class="check" style="width:24px;height:24px" data-toggle="${t.id}" aria-pressed="${t.feito}" aria-label="Marcar: ${esc(t.titulo)}">${icon('check', 12)}</button>
          <button type="button" class="body" data-open="${t.id}">
            <span class="t">${esc(t.titulo)}</span>
            <span class="m${t.atrasada ? ' late' : ''}">${t.atrasada ? 'Atrasada · ' : ''}${esc(meta(t))}</span>
          </button>
          <span class="prio ${DA.prio(t.prioridade)}" title="Prioridade ${DA.prio(t.prioridade)}"></span>
        </div>
        ${
          t.subtarefas.length && !t.feito
            ? `<div class="subs">${t.subtarefas
                .map(
                  (s) => `
          <div class="sub${s.feito ? ' done' : ''}">
            <button type="button" class="check" data-toggle="${s.id}" aria-pressed="${s.feito}" aria-label="Marcar etapa: ${esc(s.titulo)}">${icon('check', 10)}</button>
            <span>${esc(s.titulo)}</span>
          </div>`,
                )
                .join('')}</div>`
            : ''
        }
      </div>`,
      )
      .join('');
  }

  async function load() {
    const r = await get('/api/todos?aba=' + aba);
    itens = r.itens;
    render(r.contagem);
    if (aba === 'hoje' || !$('#t-bar').dataset.ok) {
      const h = aba === 'hoje' ? r.itens : (await get('/api/todos?aba=hoje')).itens;
      const feitas = h.filter((t) => t.feito).length;
      const pct = h.length ? Math.round((feitas * 100) / h.length) : 0;
      $('#t-bar span').style.width = pct + '%';
      $('#t-bar').setAttribute('aria-valuenow', pct);
      $('#t-prog-txt').textContent = `Hoje · ${feitas} de ${h.length} feitas`;
    }
  }

  $('#t-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-aba]');
    if (!b) return;
    aba = b.dataset.aba;
    store.set('aba', aba);
    load().catch(fail);
  });

  $('#t-list').addEventListener('click', async (e) => {
    const tg = e.target.closest('[data-toggle]');
    const op = e.target.closest('[data-open]');
    try {
      if (tg) {
        await patch('/api/todos/' + tg.dataset.toggle, { feito: tg.getAttribute('aria-pressed') !== 'true' });
        load();
      } else if (op) DA.openTarefa({ id: op.dataset.open });
    } catch (err) {
      fail(err);
    }
  });

  async function add() {
    const input = $('#t-quick');
    const texto = input.value.trim();
    if (!texto) {
      DA.openTarefa({ lista: aba === 'feitas' ? 'hoje' : aba });
      return;
    }
    try {
      const t = await post('/api/todos', { texto, lista: aba === 'feitas' ? 'hoje' : aba });
      input.value = '';
      if (aba !== 'feitas' && t.lista !== aba && aba !== 'hoje')
        toast('Tarefa adicionada', `Foi para ${LISTAS[t.lista]}.`);
      load();
    } catch (err) {
      fail(err);
    }
  }
  $('#t-quick').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') add();
  });
  $('#t-add').addEventListener('click', add);

  // arrastar para reordenar
  let dragId = null;
  const list = $('#t-list');
  list.addEventListener('dragstart', (e) => {
    const card = e.target.closest('.todo-card');
    if (!card) return;
    dragId = card.dataset.id;
    card.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
  });
  list.addEventListener('dragend', () => {
    $$('.todo-card', list).forEach((c) => c.classList.remove('dragging', 'drop'));
  });
  list.addEventListener('dragover', (e) => {
    const card = e.target.closest('.todo-card');
    if (!card || !dragId) return;
    e.preventDefault();
    $$('.todo-card', list).forEach((c) => c.classList.toggle('drop', c === card && c.dataset.id !== dragId));
  });
  list.addEventListener('drop', async (e) => {
    const card = e.target.closest('.todo-card');
    if (!card || !dragId || card.dataset.id === dragId) return;
    e.preventDefault();
    const ids = itens.map((t) => String(t.id)).filter((id) => id !== dragId);
    ids.splice(ids.indexOf(card.dataset.id), 0, dragId);
    dragId = null;
    try {
      await post('/api/todos/ordem', { ids });
      load();
    } catch (err) {
      fail(err);
    }
  });

  DA.onRefresh(load);
  load().catch(fail);
})();
