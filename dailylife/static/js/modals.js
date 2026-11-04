/* O que as janelas de edição dividem (modal_evento.js, modal_lembrete.js, modal_tarefa.js). */
'use strict';

(() => {
  const { $$, pad } = DA;

  DA.setupDialog = (dlg) => {
    $$('[data-close]', dlg).forEach((b) => b.addEventListener('click', () => dlg.close()));
    dlg.addEventListener('click', (e) => {
      if (e.target === dlg) dlg.close();
    });
  };
  // Próxima hora cheia, como data e hora (às 23h10 vira 00:00 do dia seguinte)
  DA.nextHourDate = () => {
    const d = DA.now();
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + 1);
    return d;
  };
  DA.nextHour = () => {
    const d = DA.nextHourDate();
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
})();
