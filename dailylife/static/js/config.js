/* Configurações: tema, inicialização, avisos, Google, celular e dados. */
'use strict';

(() => {
  const { $, $$, esc, get, post, patch, del, api, fail, toast, icon, applyTheme, hm } = DA;
  let cfg = {};
  let gPoll = null;

  async function save(data) {
    try {
      cfg = { ...cfg, ...(await patch('/api/config', data)) };
      render();
    } catch (e) {
      fail(e);
      load();
    }
  }

  function render() {
    $$('#s-tema [data-tema]').forEach((b) =>
      b.setAttribute('aria-checked', String(b.dataset.tema === cfg.tema)),
    );
    if (document.activeElement !== $('#s-nome')) $('#s-nome').value = cfg.nome || '';
    $$('.switch[data-key]').forEach((s) => s.setAttribute('aria-checked', String(!!cfg[s.dataset.key])));
    const boot = $('.switch[data-key="abrir_com_windows"]');
    boot.disabled = !cfg.inicializacao_suportada;
    $('#s-boot-help').textContent = cfg.inicializacao_suportada
      ? 'Abre sozinho ao ligar o PC'
      : 'Disponível ao rodar no Windows';
    $('#s-modo').value = cfg.modo_inicial;
    $('#s-sair-row').hidden = !cfg.desktop;
    $('#s-sync').value = String(cfg.sync_min);
    $('#s-np-ini').value = cfg.np_inicio;
    $('#s-np-fim').value = cfg.np_fim;
    $('#s-np-horas').hidden = !cfg.nao_perturbe;
    $('#s-senha-status').textContent = cfg.tem_senha
      ? 'Senha criada. Digite outra para trocar.'
      : 'Pedida ao abrir no celular';
    $('#s-backups').innerHTML = (cfg.backups || []).length
      ? 'Últimos backups: ' +
        cfg.backups.map((b) => esc(b.arquivo.replace('dailylife-', '').replace('.db', ''))).join(', ')
      : '';
  }

  async function google() {
    const g = await get('/api/google');
    const box = $('#g-status');
    clearTimeout(gPoll);
    let html = '';
    if (!g.bibliotecas) {
      html =
        '<div class="banner warn">Faltam as bibliotecas do Google. No terminal da pasta do app rode: <code>pip install -r requirements.txt</code></div>';
    } else if (!g.credenciais) {
      html = `<p class="note">Para conectar, crie as credenciais no Google Cloud e salve o arquivo <code>credentials.json</code> na pasta do Daily Life. O passo a passo está no README, na seção "Google Agenda".</p>`;
    } else if (g.conectando) {
      html = '<div class="banner">Abri o navegador. Entre na sua conta Google e autorize o Daily Life…</div>';
      gPoll = setTimeout(() => google().catch(() => {}), 2000);
    } else if (!g.conectado) {
      html = `<div class="set-row"><div class="lbl"><b>Conta Google</b><small>Os compromissos aparecem aqui e no celular</small></div>
        ${DA.isLocal ? '<button class="btn primary sm" type="button" id="g-con">Conectar</button>' : '<small class="muted">Conecte pelo computador</small>'}</div>`;
    } else {
      html = `<div class="set-row"><div class="lbl"><b>${esc(g.conta || 'Conta conectada')}</b>
          <small>${g.sincronizando ? 'Sincronizando…' : g.ultima_sync ? 'Sincronizado às ' + hm(g.ultima_sync) : 'Ainda não sincronizado'}${g.pendentes ? ` · ${g.pendentes} alteração(ões) para enviar` : ''}</small></div>
        <div style="display:flex;gap:8px"><button class="btn soft sm" type="button" id="g-sync">Sincronizar agora</button>
        <button class="btn ghost sm" type="button" id="g-off">Desconectar</button></div></div>`;
      if (g.sincronizando) gPoll = setTimeout(() => google().catch(() => {}), 2000);
    }
    if (g.erro) html += `<div class="banner warn">${esc(g.erro)}</div>`;
    box.innerHTML = html;
    $('#g-con')?.addEventListener('click', async () => {
      try {
        const r = await post('/api/google/conectar');
        toast('Google', r.mensagem);
        setTimeout(google, 800);
      } catch (e) {
        fail(e);
      }
    });
    $('#g-sync')?.addEventListener('click', async () => {
      try {
        await post('/api/google/sincronizar');
        toast('Sincronizando com o Google');
        setTimeout(() => {
          google();
          cals();
        }, 1500);
      } catch (e) {
        fail(e);
      }
    });
    $('#g-off')?.addEventListener('click', async () => {
      if (
        !confirm(
          'Desconectar a conta Google? Os compromissos do Google saem do app, mas continuam no Google.',
        )
      )
        return;
      try {
        await post('/api/google/desconectar');
        toast('Conta Google desconectada');
        google();
        cals();
        DA.pollState();
      } catch (e) {
        fail(e);
      }
    });
  }

  async function cals() {
    const r = await get('/api/calendarios');
    $('#s-cals').innerHTML = r.itens
      .map(
        (c) => `
      <div class="cal-line" data-id="${c.id}">
        ${
          c.origem === 'local'
            ? `<label class="sr-only" for="cc-${c.id}">Cor de ${esc(c.nome)}</label><input type="color" id="cc-${c.id}" value="${esc(c.cor)}" data-color>`
            : `<span class="dot" style="--c:${esc(c.cor)};width:14px;height:14px;margin:0 9px"></span>`
        }
        <span class="nm" title="${esc(c.nome)}">${esc(c.nome)}</span>
        <span class="muted" style="font-size:11px;font-weight:700">${c.origem === 'google' ? (c.somente_leitura ? 'Google · leitura' : 'Google') : 'Local'}</span>
        <button type="button" class="round plain" data-vis="${c.visivel}" aria-label="${c.visivel ? 'Esconder' : 'Mostrar'} ${esc(c.nome)}" title="${c.visivel ? 'Esconder' : 'Mostrar'}">${c.visivel ? icon('eye', 16) : icon('eye-off', 16)}</button>
        ${c.origem === 'local' ? `<button type="button" class="round plain" data-del aria-label="Apagar ${esc(c.nome)}" title="Apagar">${icon('trash', 15)}</button>` : ''}
      </div>`,
      )
      .join('');
  }

  async function load() {
    cfg = await get('/api/config');
    render();
    await Promise.all([google(), cals(), phone()]);
  }

  // ---- eventos ----
  $('#s-tema').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tema]');
    if (!b) return;
    applyTheme(b.dataset.tema);
    save({ tema: b.dataset.tema });
  });
  $('#s-nome').addEventListener('change', (e) => save({ nome: e.target.value }));
  $$('.switch[data-key]').forEach((s) =>
    s.addEventListener('click', () => {
      const k = s.dataset.key;
      save({ [k]: !cfg[k] });
    }),
  );
  $('#s-modo').addEventListener('change', (e) => save({ modo_inicial: e.target.value }));
  $('#s-sync').addEventListener('change', (e) => save({ sync_min: Number(e.target.value) }));
  $('#s-np-ini').addEventListener('change', (e) => save({ np_inicio: e.target.value }));
  $('#s-np-fim').addEventListener('change', (e) => save({ np_fim: e.target.value }));

  $('#s-senha-save').addEventListener('click', async () => {
    try {
      await post('/api/config/senha', { senha: $('#s-senha').value });
      $('#s-senha').value = '';
      toast('Senha salva', 'Os aparelhos conectados precisam entrar de novo.');
      load();
    } catch (e) {
      fail(e);
    }
  });

  // ---- celular: Tailscale (no PC) e avisos (no celular) ----
  const DOWNLOAD = 'https://tailscale.com/download';

  function tailscaleBox(c, extra = '') {
    const t = c.tailscale;
    const check =
      '<button class="btn ghost sm" type="button" data-cel="verificar">Verificar de novo</button>';
    if (!t.instalado) {
      return `<div class="banner">Instale o Tailscale neste PC e no celular (Play Store), entrando com a mesma conta.
        Baixe em <a href="${DOWNLOAD}" target="_blank" rel="noopener">tailscale.com/download</a>.</div><div class="hrow">${check}</div>`;
    }
    if (!t.conectado) {
      return `<div class="banner">O Tailscale está instalado, mas desconectado. Abra o Tailscale e entre na sua conta.</div><div class="hrow">${check}</div>`;
    }
    const devices = c.push.aparelhos;
    const pushNote = !c.push.disponivel
      ? '<div class="banner warn">Avisos no celular precisam da biblioteca cryptography. Rode o instalar.bat de novo.</div>'
      : devices
        ? `<div class="hrow center wrap-row"><span class="note">${devices} ${devices === 1 ? 'aparelho recebe' : 'aparelhos recebem'} avisos.</span>
            <button class="btn ghost sm" type="button" data-cel="teste">Enviar aviso de teste</button></div>`
        : '<p class="note">Para receber avisos, abra as Configurações no celular e toque em "Receber avisos".</p>';
    if (c.acesso && t.publicado) {
      return `${extra}<div class="qr-card">
          <div class="qr">${c.qr}</div>
          <div class="stack gap-8">
            <b>Ligado em</b><code class="addr">${esc(c.endereco)}</code>
            <ol class="note steps">
              <li>No celular, ligue o Tailscale.</li>
              <li>Leia o QR code com a câmera (ou digite o endereço no Chrome) e entre com a senha.</li>
              <li>No menu do Chrome, toque em "Instalar app" para virar um ícone.</li>
            </ol>
            <div class="hrow"><button class="btn ghost sm" type="button" data-cel="desligar">Desligar acesso</button></div>
          </div>
        </div>${pushNote}`;
    }
    return `${extra}<div class="set-row">
        <div class="lbl"><b>Acesso pelo celular</b><small>${c.tem_senha ? 'Conectado como ' + esc(t.nome || t.ip) : 'Crie a senha acima antes de ligar'}</small></div>
        <button class="btn primary sm" type="button" data-cel="ligar" ${c.tem_senha ? '' : 'disabled'}>Ligar</button>
      </div>`;
  }

  async function phone(extra = '') {
    try {
      const c = await get('/api/celular');
      if (c.local) $('#s-tailscale').innerHTML = tailscaleBox(c, extra);
      else await pushRow(c);
    } catch (e) {
      fail(e);
    }
  }

  $('#s-tailscale').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-cel]');
    if (!b) return;
    const acao = b.dataset.cel;
    if (acao === 'verificar') return phone();
    b.disabled = true;
    try {
      if (acao === 'teste') {
        const r = await post('/api/push/teste');
        toast(
          r.enviados ? 'Aviso de teste enviado' : 'Nenhum aparelho recebeu',
          r.enviados ? '' : 'Ative os avisos de novo no celular.',
        );
        return;
      }
      if (acao === 'desligar' && !confirm('Desligar o acesso pelo celular?')) return;
      const r = await post('/api/celular/' + acao);
      let extra = '';
      if (r.link) {
        extra = `<div class="banner">Falta liberar o HTTPS na sua conta do Tailscale (uma vez só).
          <a href="${esc(r.link)}" target="_blank" rel="noopener">Abrir a página do Tailscale</a>, confirmar e depois tocar em Ligar de novo.</div>`;
      } else if (!r.ok) {
        extra = `<div class="banner warn">${esc(r.mensagem || 'Não deu certo.')}</div>`;
      }
      await phone(extra);
    } catch (err) {
      fail(err);
    } finally {
      b.disabled = false;
    }
  });

  // No celular: inscrever este navegador para receber os avisos
  const pushSupported = () =>
    window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window;
  const keyBytes = (b64) => {
    const raw = atob((b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (ch) => ch.charCodeAt(0));
  };
  let pushKey = '';

  async function pushRow(c) {
    const row = $('#s-push-row');
    row.hidden = false;
    pushKey = c.push.chave;
    const btn = $('#s-push');
    if (!c.push.disponivel || !pushSupported()) {
      $('#s-push-status').textContent = !c.push.disponivel
        ? 'O PC ainda não envia avisos (falta uma biblioteca).'
        : 'Este navegador não recebe avisos. Use o Chrome pelo endereço do Tailscale.';
      btn.hidden = true;
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    btn.hidden = false;
    btn.textContent = sub ? 'Parar avisos' : 'Receber avisos';
    btn.className = 'btn sm ' + (sub ? 'ghost' : 'primary');
    $('#s-push-test').hidden = !sub;
    $('#s-push-status').textContent = sub
      ? 'Ligado: lembretes e compromissos chegam como notificação.'
      : 'Lembretes e compromissos como notificação';
  }

  $('#s-push').addEventListener('click', async () => {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await post('/api/push/cancelar', { endpoint: sub.endpoint });
        await sub.unsubscribe();
        toast('Avisos desligados neste celular');
      } else {
        if ((await Notification.requestPermission()) !== 'granted') {
          toast('Permissão negada', 'Libere as notificações do site nas configurações do Chrome.', 'err');
          return;
        }
        const nova = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: keyBytes(pushKey),
        });
        await post('/api/push/inscrever', { inscricao: nova.toJSON(), aparelho: 'Celular' });
        toast('Avisos ligados', 'Use "Testar" para conferir.');
      }
      phone();
    } catch (e) {
      fail(e);
    }
  });
  $('#s-push-test').addEventListener('click', async () => {
    try {
      const r = await post('/api/push/teste');
      if (!r.enviados) toast('Nenhum aparelho recebeu', 'Toque em Parar avisos e ligue de novo.', 'err');
    } catch (e) {
      fail(e);
    }
  });

  $('#s-cals').addEventListener('click', async (e) => {
    const line = e.target.closest('[data-id]');
    if (!line) return;
    const id = line.dataset.id;
    try {
      const vis = e.target.closest('[data-vis]');
      if (vis) {
        await patch('/api/calendarios/' + id, { visivel: vis.dataset.vis !== 'true' });
        cals();
      }
      if (e.target.closest('[data-del]')) {
        if (!confirm('Apagar este calendário? Os compromissos dele vão para outro calendário local.')) return;
        await del('/api/calendarios/' + id);
        cals();
      }
    } catch (err) {
      fail(err);
    }
  });
  $('#s-cals').addEventListener('change', async (e) => {
    if (!e.target.matches('[data-color]')) return;
    try {
      await patch('/api/calendarios/' + e.target.closest('[data-id]').dataset.id, {
        cor: e.target.value.toUpperCase(),
      });
    } catch (err) {
      fail(err);
    }
  });
  $('#s-cal-add').addEventListener('click', async () => {
    const nome = $('#s-cal-nome').value.trim();
    if (!nome) return;
    try {
      await post('/api/calendarios', { nome, cor: $('#s-cal-cor').value.toUpperCase() });
      $('#s-cal-nome').value = '';
      cals();
    } catch (e) {
      fail(e);
    }
  });

  $('#s-sair').addEventListener('click', () => {
    if (confirm('Encerrar o Daily Life? Os avisos param até você abrir o app de novo.'))
      DA.windowAction('sair');
  });

  $('#s-backup').addEventListener('click', async () => {
    try {
      const r = await post('/api/backup');
      toast('Backup feito', r.arquivo);
      load();
    } catch (e) {
      fail(e);
    }
  });
  $('#s-import').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (
      !confirm(
        'Importar substitui todos os dados atuais pelos do arquivo. Um backup é feito antes. Continuar?',
      )
    ) {
      e.target.value = '';
      return;
    }
    const fd = new FormData();
    fd.append('arquivo', file);
    try {
      await api('POST', '/api/importar', fd);
      toast('Dados importados');
      load();
    } catch (err) {
      fail(err);
    }
    e.target.value = '';
  });

  DA.onRefresh(load);
  load().catch(fail);
  if (location.hash === '#google') setTimeout(() => $('#google').scrollIntoView({ behavior: 'smooth' }), 300);
})();
