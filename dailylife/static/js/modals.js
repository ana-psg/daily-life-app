/* Janelas de edição: compromisso, lembrete e tarefa. */
'use strict';

(() => {
  const { $, $$, esc, get, post, patch, del, toast, fail, isoDate, parse, addDays, pad, icon, store } = DA;

  function setupDialog(dlg) {
    $$('[data-close]', dlg).forEach((b) => b.addEventListener('click', () => dlg.close()));
    dlg.addEventListener('click', (e) => {
      if (e.target === dlg) dlg.close();
    });
  }
  // Próxima hora cheia, como data e hora (às 23h10 vira 00:00 do dia seguinte)
  const nextHourDate = () => {
    const d = DA.now();
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + 1);
    return d;
  };
  const nextHour = () => {
    const d = nextHourDate();
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  // =============== COMPROMISSO ===============
  const evDlg = $('#dlg-evento');
  if (evDlg) {
    setupDialog(evDlg);
    const f = $('#form-evento');
    let editing = null; // compromisso aberto (null = novo)
    let ocorrencia = null; // início da ocorrência clicada, quando é uma série
    let escopo = 'todos'; // 'este' ou 'todos' (só para séries)
    let readOnly = false;
    let calId = null;
    let cals = [];
    let conflictTimer = null;
    const GOOGLE_RULE = '__google';

    const allday = () => $('#ev-allday').checked;
    const isSeries = () => !!(editing && editing.recorrente);
    function toggleAllday() {
      $$('.tm', f).forEach((el) => (el.hidden = allday()));
    }
    $('#ev-allday').addEventListener('change', () => {
      toggleAllday();
      checkConflicts();
    });

    function renderCals() {
      const lockCal = readOnly || (isSeries() && escopo === 'este') || (editing && editing.alterada);
      $('#ev-cals').innerHTML = cals
        .map(
          (c) =>
            `<button type="button" data-id="${c.id}" aria-pressed="${c.id === calId}" style="--c:${esc(c.cor)}" ${lockCal && c.id !== calId ? 'disabled' : ''}><span class="dot"></span>${esc(c.nome)}${c.origem === 'google' ? ' · G' : ''}</button>`,
        )
        .join('');
      const sel = cals.find((c) => c.id === calId);
      $('#ev-google-hint').hidden = !(sel && sel.origem === 'google') || readOnly;
    }
    $('#ev-cals').addEventListener('click', (e) => {
      const b = e.target.closest('[data-id]');
      if (!b || b.disabled) return;
      calId = Number(b.dataset.id);
      store.set('cal', String(calId));
      renderCals();
    });

    // Preenche data e hora de início e fim
    function setTimes(start, end, isAllday) {
      $('#ev-data').value = isoDate(start);
      $('#ev-ini').value = `${pad(start.getHours())}:${pad(start.getMinutes())}`;
      $('#ev-data-fim').value = isoDate(isAllday ? addDays(end, -1) : end);
      $('#ev-fim').value = `${pad(end.getHours())}:${pad(end.getMinutes())}`;
    }
    function fillTimesForScope() {
      if (!editing) return;
      if (isSeries() && escopo === 'este' && ocorrencia) {
        const dur = parse(editing.serie_fim) - parse(editing.serie_inicio);
        const s = parse(ocorrencia);
        setTimes(s, new Date(s.getTime() + dur), editing.dia_inteiro);
      } else {
        setTimes(parse(editing.serie_inicio), parse(editing.serie_fim), editing.dia_inteiro);
      }
      $('#ev-rep').disabled = readOnly || (isSeries() && escopo === 'este') || editing.alterada;
      $$('#ev-escopo [data-escopo]').forEach((b) =>
        b.setAttribute('aria-checked', String(b.dataset.escopo === escopo)),
      );
      renderCals();
    }
    $('#ev-escopo').addEventListener('click', (e) => {
      const b = e.target.closest('[data-escopo]');
      if (!b) return;
      escopo = b.dataset.escopo;
      fillTimesForScope();
      checkConflicts();
    });

    // Mudar a data de início leva a de fim junto (mantém a duração em dias)
    let lastStart = '';
    $('#ev-data').addEventListener('focus', () => {
      lastStart = $('#ev-data').value;
    });
    $('#ev-data').addEventListener('change', () => {
      const novo = $('#ev-data').value;
      if (lastStart && novo && $('#ev-data-fim').value) {
        const delta = Math.round((parse(novo) - parse(lastStart)) / 864e5);
        $('#ev-data-fim').value = isoDate(addDays(parse($('#ev-data-fim').value), delta));
      } else if (novo && !$('#ev-data-fim').value) $('#ev-data-fim').value = novo;
      lastStart = novo;
    });

    function payload() {
      const data = $('#ev-data').value;
      const dataFim = $('#ev-data-fim').value || data;
      const p = {
        titulo: $('#ev-titulo').value.trim(),
        calendar_id: calId,
        dia_inteiro: allday(),
        local: $('#ev-local').value.trim(),
        notas: $('#ev-notas').value.trim(),
        aviso_min: $('#ev-aviso').value === '' ? null : Number($('#ev-aviso').value),
      };
      const rep = $('#ev-rep').value;
      if (rep !== GOOGLE_RULE && !$('#ev-rep').disabled) p.repeticao = rep; // senão mantém a regra
      if (!data) throw new Error('Escolha a data.');
      if (dataFim < data) throw new Error('A data de término precisa ser igual ou depois da de início.');
      if (p.dia_inteiro) {
        p.inicio = `${data}T00:00`;
        p.fim = `${isoDate(addDays(parse(dataFim), 1))}T00:00`;
      } else {
        const ini = $('#ev-ini').value;
        const fim = $('#ev-fim').value;
        if (!ini || !fim) throw new Error('Informe o horário de início e de fim.');
        p.inicio = `${data}T${ini}`;
        p.fim = `${dataFim}T${fim}`;
        if (dataFim === data && fim === ini) throw new Error('O fim precisa ser depois do início.');
        if (dataFim === data && fim < ini) p.fim = `${isoDate(addDays(parse(data), 1))}T${fim}`; // passa da meia-noite
      }
      if (isSeries()) {
        p.escopo = escopo;
        if (escopo === 'este') p.ocorrencia = ocorrencia;
      }
      return p;
    }

    async function checkConflicts() {
      clearTimeout(conflictTimer);
      conflictTimer = setTimeout(async () => {
        const warn = $('#ev-warn');
        try {
          if (readOnly) {
            warn.hidden = true;
            return;
          }
          const p = payload();
          if (p.dia_inteiro) {
            warn.hidden = true;
            return;
          }
          const q = new URLSearchParams({ inicio: p.inicio, fim: p.fim });
          if (editing) q.set('ignorar', editing.id);
          if (editing && ocorrencia && escopo === 'este') q.set('ocorrencia', ocorrencia);
          const r = await get('/api/eventos/conflitos?' + q);
          warn.hidden = !r.itens.length;
          warn.textContent = r.itens.length
            ? 'Conflito de horário com: ' +
              r.itens.map((c) => `${c.titulo} (${c.inicio.slice(11, 16)})`).join(', ')
            : '';
        } catch (_) {
          warn.hidden = true;
        }
      }, 300);
    }
    ['#ev-data', '#ev-ini', '#ev-fim', '#ev-data-fim'].forEach((s) =>
      $(s).addEventListener('change', checkConflicts),
    );
    $('#ev-ini').addEventListener('change', () => {
      // Início depois do fim no mesmo dia: o fim vai para 1 h depois (pode virar o dia)
      if (!$('#ev-ini').value || !$('#ev-data').value) return;
      if ($('#ev-data-fim').value === $('#ev-data').value && $('#ev-fim').value <= $('#ev-ini').value) {
        const s = parse(`${$('#ev-data').value}T${$('#ev-ini').value}`);
        const e = new Date(s.getTime() + 3600e3);
        $('#ev-data-fim').value = isoDate(e);
        $('#ev-fim').value = `${pad(e.getHours())}:${pad(e.getMinutes())}`;
      }
    });

    function setReadOnly(on) {
      readOnly = on;
      $$('input, select, textarea', f).forEach((el) => (el.disabled = on));
      $('#ev-ro').hidden = !on;
      f.querySelector('button[type=submit]').hidden = on;
    }

    // ev: {} novo · {id} existente · {id, ocorrencia} ocorrência de série · {data, hora} novo nesse horário
    DA.openEvento = async (ev = {}) => {
      try {
        const r = await get('/api/calendarios');
        editing = ev.id ? await get('/api/eventos/' + ev.id) : null;
        ocorrencia = editing && editing.recorrente ? ev.ocorrencia || null : null;
        escopo = ocorrencia ? 'este' : 'todos';
        cals = r.itens.filter(
          (c) => (c.visivel && !c.somente_leitura) || (editing && c.id === editing.calendar_id),
        );
        if (!cals.length) {
          toast('Nenhum calendário disponível', 'Crie ou mostre um calendário nas Configurações.', 'err');
          return;
        }
        f.reset();
        setReadOnly(false);
        $('#ev-warn').hidden = true;
        $('#ev-rep').querySelector(`option[value="${GOOGLE_RULE}"]`)?.remove();
        $('#ev-escopo-box').hidden = !isSeries();
        if (editing) {
          const ro = editing.somente_leitura;
          $('#ev-h').textContent = ro ? 'Detalhes do compromisso' : 'Editar compromisso';
          $('#ev-del').hidden = ro;
          $('#ev-titulo').value = editing.titulo;
          $('#ev-allday').checked = editing.dia_inteiro;
          if (editing.rrule) {
            $('#ev-rep').insertAdjacentHTML(
              'beforeend',
              `<option value="${GOOGLE_RULE}">Regra personalizada do Google</option>`,
            );
            $('#ev-rep').value = GOOGLE_RULE;
          } else $('#ev-rep').value = editing.repeticao || '';
          $('#ev-local').value = editing.local || '';
          $('#ev-notas').value = editing.notas || '';
          $('#ev-aviso').value = editing.aviso_min === null ? '' : String(editing.aviso_min);
          calId = editing.calendar_id;
          setReadOnly(ro);
          if (ro) $('#ev-escopo-box').hidden = true;
          fillTimesForScope();
        } else {
          $('#ev-h').textContent = 'Novo compromisso';
          $('#ev-del').hidden = true;
          $('#ev-rep').disabled = false;
          const start = ev.data
            ? parse(`${ev.data}T${ev.hora || nextHour()}`)
            : ev.hora
              ? parse(`${isoDate(DA.now())}T${ev.hora}`)
              : nextHourDate();
          setTimes(start, new Date(start.getTime() + 3600e3), false);
          $('#ev-aviso').value = '15';
          const last = Number(store.get('cal'));
          calId = cals.some((c) => c.id === last) ? last : cals[0].id;
          renderCals();
        }
        toggleAllday();
        evDlg.showModal();
        if (!readOnly) $('#ev-titulo').focus();
        if (editing && !readOnly) checkConflicts();
      } catch (e) {
        fail(e);
      }
    };

    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (readOnly) return;
      try {
        const p = payload();
        if (!p.titulo) throw new Error('Dê um título ao compromisso.');
        const saved = editing ? await patch('/api/eventos/' + editing.id, p) : await post('/api/eventos', p);
        evDlg.close();
        if (saved.conflitos && saved.conflitos.length) {
          toast(
            'Salvo, mas com conflito',
            saved.conflitos.map((c) => `${c.titulo} às ${c.inicio.slice(11, 16)}`).join(', '),
          );
        } else toast(editing ? 'Compromisso atualizado' : 'Compromisso criado', p.titulo);
        DA.refresh();
      } catch (err) {
        fail(err);
      }
    });
    $('#ev-del').addEventListener('click', async () => {
      if (!editing || readOnly) return;
      const so = isSeries() && escopo === 'este' && ocorrencia;
      const quando = so
        ? ` de ${DA.DIAS[DA.weekday(parse(ocorrencia))].toLowerCase()}, ${parse(ocorrencia).getDate()}/${pad(parse(ocorrencia).getMonth() + 1)}`
        : '';
      const msg = so
        ? `Excluir só "${editing.titulo}"${quando}?`
        : isSeries()
          ? `Excluir "${editing.titulo}" e todas as repetições?`
          : `Excluir "${editing.titulo}"?`;
      if (!confirm(msg)) return;
      const q = so ? `?escopo=este&ocorrencia=${encodeURIComponent(ocorrencia)}` : '';
      try {
        await del('/api/eventos/' + editing.id + q);
        evDlg.close();
        toast('Compromisso excluído');
        DA.refresh();
      } catch (e) {
        fail(e);
      }
    });
  }

  // =============== LEMBRETE ===============
  const rmDlg = $('#dlg-lembrete');
  if (rmDlg) {
    setupDialog(rmDlg);
    const f = $('#form-lembrete');
    let editing = null;
    let cor = 'amarelo';
    let dias = new Set();

    function syncRepeat() {
      const v = $('#rm-rep').value;
      $('#rm-horas-box').hidden = v !== 'horas';
      $('#rm-dias-box').hidden = v !== 'dias';
      $('#rm-rec-hint').hidden = v === '';
    }
    $('#rm-rep').addEventListener('change', syncRepeat);
    const renderDays = () =>
      $$('#rm-dias button').forEach((b) =>
        b.setAttribute('aria-pressed', String(dias.has(Number(b.dataset.d)))),
      );
    const renderColor = () =>
      $$('#rm-cores button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.cor === cor)));
    $('#rm-dias').addEventListener('click', (e) => {
      const b = e.target.closest('[data-d]');
      if (!b) return;
      const d = Number(b.dataset.d);
      dias.has(d) ? dias.delete(d) : dias.add(d);
      renderDays();
    });
    $('#rm-cores').addEventListener('click', (e) => {
      const b = e.target.closest('[data-cor]');
      if (b) {
        cor = b.dataset.cor;
        renderColor();
      }
    });

    function rule() {
      const v = $('#rm-rep').value;
      if (v === 'horas') return `horas:${Math.max(1, Math.min(23, Number($('#rm-horas').value) || 2))}`;
      if (v === 'dias') {
        if (!dias.size) throw new Error('Escolha pelo menos um dia da semana.');
        return 'dias:' + Array.from(dias).sort().join(',');
      }
      return v;
    }

    DA.openLembrete = async (rem = {}) => {
      try {
        editing = rem.id ? await get('/api/lembretes/' + rem.id) : null;
        f.reset();
        $('#rm-h').textContent = editing ? 'Editar lembrete' : 'Novo lembrete';
        $('#rm-del').hidden = !editing;
        dias = new Set();
        if (editing) {
          $('#rm-titulo').value = editing.titulo;
          $('#rm-desc').value = editing.descricao || '';
          $('#rm-data').value = editing.quando.slice(0, 10);
          $('#rm-hora').value = editing.quando.slice(11, 16);
          const r = editing.repeticao || '';
          if (r.startsWith('horas:')) {
            $('#rm-rep').value = 'horas';
            $('#rm-horas').value = r.split(':')[1];
          } else if (r.startsWith('dias:')) {
            $('#rm-rep').value = 'dias';
            r.split(':')[1]
              .split(',')
              .forEach((d) => dias.add(Number(d)));
          } else $('#rm-rep').value = r;
          cor = editing.cor || 'amarelo';
        } else {
          $('#rm-data').value = rem.data || isoDate(DA.now());
          $('#rm-hora').value = rem.hora || nextHour();
          if (!rem.data && !rem.hora) $('#rm-data').value = isoDate(nextHourDate());
          cor = 'amarelo';
        }
        syncRepeat();
        renderDays();
        renderColor();
        rmDlg.showModal();
        $('#rm-titulo').focus();
      } catch (e) {
        fail(e);
      }
    };

    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const titulo = $('#rm-titulo').value.trim();
        if (!titulo) throw new Error('Dê um título ao lembrete.');
        if (!$('#rm-data').value || !$('#rm-hora').value) throw new Error('Informe data e hora.');
        const p = {
          titulo,
          descricao: $('#rm-desc').value.trim(),
          quando: `${$('#rm-data').value}T${$('#rm-hora').value}`,
          repeticao: rule(),
          cor,
        };
        if (editing) await patch('/api/lembretes/' + editing.id, p);
        else await post('/api/lembretes', p);
        rmDlg.close();
        toast(editing ? 'Lembrete atualizado' : 'Lembrete criado', titulo);
        DA.refresh();
      } catch (err) {
        fail(err);
      }
    });
    $('#rm-del').addEventListener('click', async () => {
      if (!editing || !confirm(`Excluir o lembrete "${editing.titulo}"?`)) return;
      try {
        await del('/api/lembretes/' + editing.id);
        rmDlg.close();
        toast('Lembrete excluído');
        DA.refresh();
      } catch (e) {
        fail(e);
      }
    });
  }

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
