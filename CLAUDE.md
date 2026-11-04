# Daily Life

App desktop (Windows): to-do, lembretes, compromissos e calendário, com modo widget.
Flask + pywebview + SQLite.

## Estrutura
- `main.py` abre o app. Pacote `dailylife/`: `core/` (regras), `web/` (app.py, security.py, pages.py, api.py
  Blueprint /api, net.py), `desktop/` (app.py, windows.py, tray.py, scheduler.py, notifier.py, startup.py),
  `sync/` (google.py login e rodada, pull.py, push.py, convert.py, common.py), `db.py` (schema e migrações),
  `config.py`.
- `tests/` (pytest, com os testes antigos em unittest + e2e_telas.py com Playwright) e `tools/` (seed, diagnóstico, ícones).

## Regras
- Idioma: código (funções, variáveis, módulos) em inglês; dados e textos em português (colunas do banco,
  chaves da API e do JSON, mensagens, telas). Não renomear colunas do banco: exportações e bancos existentes
  dependem delas.
- Visual: cores em static/css/tokens.css (tema claro e [data-theme="escuro"]),
  fonte Plus Jakarta Sans, cantos de 14 a 30 px, sem bordas pesadas, barra de navegação escura em pílula.
- Toda cor nova entra como token nos DOIS temas. Cores de calendário usam --c + color-mix (classe .ev).
- tokens.css também tem as escalas (--space-*, --radius-*, --text-*) e --hour (altura de uma hora na linha
  do tempo, lida pelo timeline.js). Cantos de 14 a 30 px nos cartões; itens dentro de um cartão (menu,
  chips, células) usam --radius-sm (12 px) para ficarem concêntricos.
- Nada de style="" gerado no JS também: use as classes utilitárias de responsivo.css (exceto --c, --n e
  posições calculadas como top/left).
- Nenhuma tela pode rolar para o lado entre 390 px e 1280 px (o e2e_telas.py confere em 900 px).
- Nada de style="" nos templates (exceto --c e larguras de barra de progresso); use as classes de static/css.
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
  Inteligente: o app tem plano B (Edge --app e balão da bandeja). tools/diagnostico.py mostra o que carregou.
- Todos os calendários do Google entram no app, visíveis por padrão.
- Nada de dados pessoais no Git: data/, credentials.json, token.json.
- JS sem framework e sem build: um arquivo por tela em static/js, utilidades em api.js (objeto DA).
- Textos da interface em português do Brasil. Acessibilidade: botões reais, aria-label em botões só com ícone.
- Mantenha o .exe funcionando (packaging/DailyLife.spec): recursos novos fora de dailylife/ entram em datas.
- Dados: no .exe ficam em %APPDATA%\Daily Life; rodando pelo código, em data/ (config.default_data_dir).

## Antes de terminar uma mudança
- `ruff check . && ruff format --check .`
- `npx prettier --check "dailylife/static/**/*.{js,css}"`
- `python -m pytest` (dependências em requirements-dev.txt)
- Mudou tela ou CSS: `python tests/e2e_telas.py` e olhar as capturas em data/telas.

## Como rodar
- App: python main.py --debug
- Instalador: .\build.ps1 (saída em dist/)
- Só no navegador: python -m dailylife.web.app -> http://127.0.0.1:5055
- Dados de exemplo: python tools/seed.py --forcar
