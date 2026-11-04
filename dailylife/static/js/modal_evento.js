/* Janela de edição: compromisso. */
'use strict';

(() => {
  const {
    $,
    $$,
    esc,
    get,
    post,
    patch,
    del,
    toast,
    fail,
    isoDate,
    parse,
    addDays,
    pad,
    store,
    setupDialog,
    nextHourDate,
    nextHour,
  } = DA;

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
})();
