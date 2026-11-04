/* Janela de edição: tarefa. */
'use strict';

(() => {
  const { $, $$, esc, get, post, patch, del, toast, fail, icon, setupDialog } = DA;

  // =============== TAREFA ===============
  const tdDlg = $('#dlg-tarefa');
  if (tdDlg) {
    setupDialog(tdDlg);
    const f = $('#form-tarefa');
    let editing = null;
    let prio = 'media';
    let pendingSubs = [];

    const renderPriority = () =>
      $$('#td-prio button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.p === prio)));
    $('#td-prio').addEventListener('click', (e) => {
      const b = e.target.closest('[data-p]');
      if (b) {
        prio = b.dataset.p;
        renderPriority();
      }
    });

    function renderSubtasks() {
      const list = editing
        ? editing.subtarefas
        : pendingSubs.map((t, i) => ({ id: 'n' + i, titulo: t, feito: false }));
      $('#td-subs').innerHTML = list
        .map(
          (s) => `
        <div class="item sub${s.feito ? ' done' : ''}" data-id="${s.id}">
          <button type="button" class="check" aria-pressed="${s.feito}" aria-label="Marcar subtarefa: ${esc(s.titulo)}" ${editing ? '' : 'disabled'}>${icon('check', 10)}</button>
          <span style="flex:1">${esc(s.titulo)}</span>
          <button type="button" class="round plain" style="width:30px;height:30px" aria-label="Remover subtarefa" data-rm>${icon('x', 12)}</button>
        </div>`,
        )
        .join('');
    }
    $('#td-subs').addEventListener('click', async (e) => {
      const row = e.target.closest('[data-id]');
      if (!row) return;
      const id = row.dataset.id;
      try {
        if (e.target.closest('[data-rm]')) {
          if (editing) {
            await del('/api/todos/' + id);
            editing = await get('/api/todos/' + editing.id);
          } else pendingSubs.splice(Number(id.slice(1)), 1);
          renderSubtasks();
        } else if (e.target.closest('.check') && editing) {
          const s = editing.subtarefas.find((x) => String(x.id) === id);
          await patch('/api/todos/' + id, { feito: !s.feito });
          editing = await get('/api/todos/' + editing.id);
          renderSubtasks();
        }
      } catch (err) {
        fail(err);
      }
    });
    $('#td-sub-new').addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const t = e.target.value.trim();
      if (!t) return;
      try {
        if (editing) {
          await post('/api/todos', { titulo: t, parent_id: editing.id });
          editing = await get('/api/todos/' + editing.id);
        } else pendingSubs.push(t);
        e.target.value = '';
        renderSubtasks();
      } catch (err) {
        fail(err);
      }
    });

    DA.openTarefa = async (todo = {}) => {
      try {
        editing = todo.id ? await get('/api/todos/' + todo.id) : null;
        pendingSubs = [];
        f.reset();
        $('#td-h').textContent = editing ? 'Editar tarefa' : 'Nova tarefa';
        $('#td-del').hidden = !editing;
        $('#td-subs-box').hidden = !!(editing && editing.parent_id);
        if (editing) {
          $('#td-titulo').value = editing.titulo;
          $('#td-lista').value = editing.lista;
          $('#td-lista').disabled = !!editing.parent_id;
          $('#td-venc').value = (editing.vencimento || '').slice(0, 10);
          $('#td-notas').value = editing.notas || '';
          prio = editing.prioridade;
        } else {
          $('#td-lista').disabled = false;
          $('#td-lista').value = todo.lista || 'hoje';
          prio = 'media';
        }
        renderPriority();
        renderSubtasks();
        tdDlg.showModal();
        $('#td-titulo').focus();
      } catch (e) {
        fail(e);
      }
    };

    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const p = {
          titulo: $('#td-titulo').value.trim(),
          notas: $('#td-notas').value.trim(),
          prioridade: prio,
          vencimento: $('#td-venc').value || null,
        };
        if (!p.titulo) throw new Error('Dê um título à tarefa.');
        if (!(editing && editing.parent_id)) p.lista = $('#td-lista').value;
        if (editing) await patch('/api/todos/' + editing.id, p);
        else {
          const t = await post('/api/todos', p);
          for (const s of pendingSubs) await post('/api/todos', { titulo: s, parent_id: t.id });
        }
        tdDlg.close();
        DA.refresh();
      } catch (err) {
        fail(err);
      }
    });
    tdDlg.addEventListener('close', () => {
      if (editing) DA.refresh();
    });
    $('#td-del').addEventListener('click', async () => {
      if (!editing || !confirm(`Excluir a tarefa "${editing.titulo}"?`)) return;
      try {
        await del('/api/todos/' + editing.id);
        editing = null;
        tdDlg.close();
        toast('Tarefa excluída');
        DA.refresh();
      } catch (e) {
        fail(e);
      }
    });
  }
})();
