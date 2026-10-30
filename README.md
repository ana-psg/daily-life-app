# Daily Life

App de produtividade para Windows. Abre junto com o PC e junta **to-do, lembretes, compromissos e calendário** numa janela só, com modo widget, tema claro e escuro, avisos do Windows, Google Agenda e acesso pelo celular.

Feito com Python: Flask (telas e API) + pywebview (janela) + SQLite (dados no seu PC).

---

## 1. Instalar (uma vez)

1. Instale o **Python 3.12** em [python.org](https://www.python.org/downloads/). Na instalação, marque **"Add python.exe to PATH"**.
2. Baixe este repositório (botão **Code > Download ZIP**) e descompacte onde quiser (ex.: `Documentos\dailylife`).
3. Dê dois cliques em **`instalar.bat`**. Ele cria o ambiente `.venv` e instala tudo. No fim pergunta se você quer dados de exemplo.
4. Abra o app com **`DailyLife.bat`**.

> O WebView2 (motor da janela) já vem no Windows 10 e 11. Se a janela abrir em branco, instale o "Microsoft Edge WebView2 Runtime".

> O app usa sempre o horário de São Paulo. Em outro fuso, mude `TZ` em `dailylife/config.py`.

Depois de abrir, coloque o seu nome em **Configurações** para ele aparecer na saudação do painel.

## 2. Usar

| Onde | O que faz |
| --- | --- |
| Painel | Próximo compromisso, to-do de hoje com progresso, lembretes e a semana. Dois cliques num horário vazio criam um compromisso. |
| Widget | Versão compacta, sem bordas. Arraste pelo topo (onde fica a hora). |
| Calendário | Visões Dia, Semana e Mês; mostrar ou esconder calendários. |
| To-do | Abas Hoje, Semana, Projetos, Feitas; subtarefas; arrastar para reordenar. |
| Lembretes | Cartões com repetição, adiar 1 h e marcar como feito. |
| Configurações | Tema, inicialização, avisos, Google, celular, backup. |

**Compromissos que se repetem:** ao abrir um deles, escolha **Só este** (muda ou exclui só aquele dia) ou **Todos** (muda a série inteira). Compromissos de calendários do Google só de leitura (como feriados) abrem só para ver.

**Campo rápido de tarefa:** `Ligar pro banco amanhã !alta #semana` cria a tarefa com vencimento amanhã, prioridade alta, na lista Semana.

**Lembretes recorrentes:** ao marcar, contam como concluídos hoje e voltam na próxima vez (normalmente no dia seguinte). "A cada 2 h" avisa de 2 em 2 horas até você marcar. Semanais e mensais que passaram sem marcar ficam como atrasados até você marcar. No horário de "não perturbe", os lembretes esperam e avisam quando ele acabar.

**Atalhos de teclado:** `N` tarefa · `C` compromisso · `L` lembrete · `W` painel/widget · `T` tema · `1` a `4` trocam de tela · `Esc` fecha.

**Fechar a janela não fecha o app:** ele fica no ícone da bandeja (perto do relógio) para os avisos funcionarem. Para sair de verdade: clique com o botão direito no ícone > **Sair do Daily Life**.

## 3. Abrir junto com o Windows

Em **Configurações > Ao ligar o PC**, ligue **Abrir junto com o Windows** e escolha se abre como painel ou widget. Ligue **Widget sempre por cima** para ele ficar como nota adesiva.

Isso cria uma entrada em `HKEY_CURRENT_USER\...\Run` (não precisa de administrador). Se mudar a pasta de lugar, abra o app uma vez pelo `.bat` que ele atualiza o caminho.

## 4. Google Agenda

Todos os calendários da sua conta entram no app (dá para esconder cada um). O que você cria num calendário do Google aparece no celular; calendários locais (Trabalho, Pessoal, Saúde, Projetos) ficam só no PC.

**Passo a passo (uma vez, uns 10 minutos):**

1. Entre em [console.cloud.google.com](https://console.cloud.google.com) com sua conta e crie um projeto (ex.: "Daily Life").
2. Ative a **Google Calendar API**: menu > APIs e serviços > Biblioteca > "Google Calendar API" > Ativar.
3. Menu > **Google Auth Platform > Branding** > Get started. Nome do app: Daily Life; e-mail de suporte: o seu. Em **Audience**, escolha **External**. Termine o assistente.
4. Em **Google Auth Platform > Audience > Test users**, adicione o seu próprio e-mail.
5. Em **Google Auth Platform > Clients > Create client**, tipo **Desktop app**, nome "Daily Life". Baixe o JSON.
6. Renomeie o arquivo para **`credentials.json`** e coloque na pasta do Daily Life (junto do `main.py`).
7. No app: **Configurações > Google Agenda > Conectar**. O navegador abre; entre na conta e autorize. Pode aparecer "O Google não verificou este app": clique em Avançado > Acessar Daily Life (o app é seu).

**Importante:** com o app em modo "Testing", o Google pode pedir login de novo depois de alguns dias. Se aparecer o aviso "O acesso ao Google expirou", é só clicar em Conectar de novo. Para evitar, em **Audience** clique em **Publish app** (para uso pessoal não precisa de verificação; só aparece o aviso do passo 7).

Como a sincronização funciona: envia o que mudou no app, baixa o que mudou no Google (a cada 5 min, ou no intervalo escolhido) e, em conflito, vale a alteração mais recente. Sem internet, as mudanças ficam guardadas e vão quando a conexão voltar.

## 5. Usar no celular (4G ou Wi-Fi, pelo Tailscale)

O [Tailscale](https://tailscale.com) cria uma rede privada só entre os seus aparelhos. O celular abre o app do PC de qualquer lugar, com HTTPS, e os dados continuam só no PC. O plano Personal é grátis para uso pessoal. O PC precisa estar ligado (o Google Agenda continua no celular mesmo com o PC desligado).

**Uma vez só (uns 10 minutos):**

1. Instale o Tailscale no PC ([tailscale.com/download](https://tailscale.com/download)) e no celular (Play Store), e entre com a **mesma conta** nos dois.
2. No PC: **Configurações > Usar no celular**: crie uma **senha** (mínimo 6 caracteres) e toque em **Ligar**.
3. Na primeira vez, o Tailscale pede para liberar o HTTPS na sua conta: o app mostra o link. Abra, confirme e toque em **Ligar** de novo. (Isso publica o nome do PC, como `notebook.tail1234.ts.net`, num registro público de certificados; o acesso continua só para os seus aparelhos.)
4. Aparece um **QR code**. No celular, com o Tailscale ligado, leia o QR com a câmera, abra no Chrome e entre com a senha.
5. No menu do Chrome, toque em **Instalar app**: vira um ícone na tela inicial.
6. No celular, em **Configurações > Avisos neste celular**, toque em **Receber avisos** e permita as notificações. Use **Testar** para conferir.

Os avisos chegam com os botões **Resolvido** e **Adiar 1 h**, iguais aos do Windows, nos mesmos horários (respeitam o "não perturbe"). Trocar a senha desconecta os aparelhos; para parar tudo, toque em **Desligar acesso** no PC.

## 6. Dados e backup

- Tudo fica em `data/dailylife.db`. Backup automático diário em `data/backups` (ficam os últimos 14).
- **Exportar/Importar** em Configurações gera ou lê um JSON com tudo (a senha não vai junto).
- Logs em `data/dailylife.log` (útil se algo der errado).
- `data/`, `credentials.json` e `token.json` nunca vão para o Git.

## 7. Gerar o .exe (opcional)

Rode `gerar_exe.bat`. O executável fica em `dist\DailyLife\DailyLife.exe`. Copie para lá a pasta `data` e o `credentials.json` se quiser levar seus dados.

## 8. Para desenvolver

```
.venv\Scripts\activate
python main.py --debug              # app com DevTools
python -m dailylife.web.app         # só no navegador: http://127.0.0.1:5055
python -m unittest discover -s tests -v
python tests/e2e_telas.py           # robô que clica em todas as telas (precisa do Playwright)
python tools/seed.py --forcar       # recria os dados de exemplo
ruff check . && ruff format .       # padrão do Python
npx prettier --write "dailylife/static/**/*.{js,css}"   # padrão do JavaScript e do CSS
diagnostico.bat                     # o que carregou e o que o Windows bloqueou
```

Regras do projeto em `CLAUDE.md`. Estrutura:

```
main.py                 abre o app (é o que o DailyLife.bat e o .exe rodam)
dailylife/
  config.py             nome, pastas, porta e hora de São Paulo
  db.py                 SQLite: schema atual + migrações numeradas (PRAGMA user_version)
  core/                 regras: todos, reminders, events, calendars, settings, dashboard,
                        recurrence, backup
  web/                  app.py (telas e segurança), api.py (API JSON), net.py
  desktop/              app.py (janelas, bandeja), scheduler.py (avisos, Google, backup a cada 30 s),
                        notifier.py (avisos do Windows), startup.py (abrir com o Windows)
  sync/google.py        login OAuth e sincronização com o Google Agenda
  tailscale.py          acesso pelo celular (tailscale serve) · qr.py: QR code em SVG
  push.py               avisos no celular (Web Push)
  templates/            HTML (Jinja); _icons.html tem todos os ícones
  static/               css (tokens.css = cores dos temas), js (um por tela), img
tests/                  testes (unittest) e o robô das telas
tools/                  seed.py, diagnostico.py, make_icons.py
```

## 9. Controle de Aplicativos Inteligente do Windows

O Windows 11 pode bloquear partes do app que não têm assinatura digital (bibliotecas baixadas pelo `instalar.bat`). O Daily Life continua funcionando mesmo assim:

- Se a janela própria for bloqueada, ele abre no **Edge em modo aplicativo** (sem o widget sem bordas e sem "sempre por cima").
- Se os avisos com botões forem bloqueados, os avisos saem como **balão do ícone da bandeja**.

Para ver exatamente o que foi bloqueado, dê dois cliques em **`diagnostico.bat`**. O resultado também fica em `data/diagnostico.txt`. Para ter tudo funcionando, dá para desligar o recurso em **Segurança do Windows > Controle de aplicativos e do navegador > Configurações do Controle de Aplicativos Inteligente**. Desde a atualização de abril de 2026 do Windows 11 é possível ligá-lo de novo depois sem reinstalar o Windows.

## 10. Problemas comuns

| Problema | Solução |
| --- | --- |
| Nada acontece ao abrir | Rode `diagnostico.bat`. Veja também `data/dailylife.log` ou rode `python main.py` no terminal. |
| Abriu no Edge em vez da janela própria | A janela foi bloqueada pelo Windows. Veja a seção 9. |
| "A porta 5055 está em uso" | Outro programa usa a porta. Defina a variável `DAILYLIFE_PORT` com outro número. |
| Avisos não aparecem | Configurações do Windows > Notificações: deixe ligadas para "Python". Confira o "Não perturbe" do app. |
| Celular não abre | O Tailscale está ligado no celular e no PC? O acesso aparece como ligado nas Configurações do PC? O PC está ligado e com o app aberto? |
| Avisos não chegam no celular | Toque em Testar. Confira se as notificações do Chrome estão permitidas e se a economia de bateria não bloqueia o Chrome. |
| Google pede login de novo | Normal no modo "Testing". Veja a seção 4. |
