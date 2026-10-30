# Daily Life

App desktop (Windows): to-do, lembretes, compromissos e calendário, com modo widget.
Flask + pywebview + SQLite.

## Estrutura
- `main.py` abre o app. Pacote `dailylife/`: `core/` (regras), `web/` (app.py telas e segurança, api.py
  Blueprint /api, net.py), `desktop/` (janelas, bandeja, agendador, avisos, registro), `sync/google.py`,
  `db.py` (schema e migrações), `config.py`.
- `tests/` (unittest + e2e_telas.py com Playwright) e `tools/` (seed, diagnóstico, ícones).

## Regras
- Idioma: código (funções, variáveis, módulos) em inglês; dados e textos em português (colunas do banco,
  chaves da API e do JSON, mensagens, telas). Não renomear colunas do banco: exportações e bancos existentes
  dependem delas.
- Visual: cores em static/css/tokens.css (tema claro e [data-theme="escuro"]),
  fonte Plus Jakarta Sans, cantos de 14 a 30 px, sem bordas pesadas, barra de navegação escura em pílula.
- Toda cor nova entra como token nos DOIS temas. Cores de calendário usam --c + color-mix (classe .ev).
- Nada de style="" nos templates (exceto --c e larguras de barra de progresso); use as classes de app.css.
- Ícones só em templates/_icons.html: Jinja usa icon('nome'), o JS usa DA.icon('nome', tamanho).
- Banco: SCHEMA em db.py é o formato atual (bancos novos). Para mudar: altere SCHEMA E acrescente uma função
  no fim de MIGRATIONS (bancos existentes; roda uma vez, guardada em PRAGMA user_version). Nunca apagar o banco.
- Regras de negócio ficam em core/; as rotas de web/api.py só chamam core e devolvem JSON.
- Erros de dado: levantar core.ValidationError com mensagem em português (vira HTTP 400).
- Datas em texto ISO 'YYYY-MM-DDTHH:MM', horário de São Paulo sem fuso (config.now(), config.iso()).
- Lembrete recorrente marcado conta como concluído no dia e volta na próxima ocorrência.
  Semanais e mensais perdidos ficam atrasados até serem marcados; diários e "a cada N h" voltam para hoje.
- Compromissos: série = linha com repeticao (nossas regras) ou rrule (regra do Google). Ocorrência alterada =
  linha com serie_id + ocorrencia (início original); cancelado=1 = ocorrência excluída. "Só este" usa escopo='este'.
- Google: baixa com singleEvents=False (séries como regra + exceções). SYNC_VERSION em sync/google.py controla
  a migração de bancos antigos.
- Segurança: o servidor escuta só em 127.0.0.1. O celular chega pelo `tailscale serve` (HTTPS *.ts.net), que
  conecta de 127.0.0.1: web/net.py is_local_request() trata como de fora qualquer pedido com Host *.ts.net ou
  cabeçalhos de intermediário (Tailscale-User-Login, X-Forwarded-*), e esses pedem a senha. host_allowed()
  aceita localhost, IP e *.ts.net; POST de outra origem é recusado. Telas usam DA.now(), nunca new Date().
- Celular: dailylife/tailscale.py (status, serve --bg, off), dailylife/qr.py (QR em SVG sem biblioteca),
  dailylife/push.py (Web Push com VAPID e aes128gcm só com cryptography; testado contra o RFC 8291).
  Avisos vão para o celular junto com os do Windows (notifier.notify com nativo=True).
- As telas consultam só /api/estado (avisos + Google) a cada 20 s; painel e widget recarregam a cada minuto
  com DA.onRefresh(load, { auto: true }). Preferências do aparelho em DA.store (chaves dailylife.*).
- Partes nativas (pywebview, win11toast, pystray) podem ser bloqueadas pelo Controle de Aplicativos
  Inteligente: o app tem plano B (Edge --app e balão da bandeja). diagnostico.bat mostra o que carregou.
- Todos os calendários do Google entram no app, visíveis por padrão.
- Nada de dados pessoais no Git: data/, credentials.json, token.json.
- JS sem framework e sem build: um arquivo por tela em static/js, utilidades em api.js (objeto DA).
- Textos da interface em português do Brasil. Acessibilidade: botões reais, aria-label em botões só com ícone.
- Mantenha o .exe funcionando (gerar_exe.bat): recursos novos fora de dailylife/ precisam de --add-data.

## Antes de terminar uma mudança
- `ruff check . && ruff format --check .`
- `npx prettier --check "dailylife/static/**/*.{js,css}"`
- `python -m unittest discover -s tests`
- Mudou tela ou CSS: `python tests/e2e_telas.py` e olhar as capturas em data/telas.

## Como rodar
- App: DailyLife.bat (ou: python main.py --debug)
- Só no navegador: python -m dailylife.web.app -> http://127.0.0.1:5055
- Dados de exemplo: python tools/seed.py --forcar
