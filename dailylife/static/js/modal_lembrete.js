/* Janela de edição: lembrete. */
'use strict';

(() => {
  const { $, $$, get, post, patch, del, toast, fail, isoDate, setupDialog, nextHourDate, nextHour } = DA;

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
})();
