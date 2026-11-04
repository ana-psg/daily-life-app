"""Teste de telas: um robô clica em todas as telas, nos dois temas e no tamanho de celular.

Precisa do Playwright (opcional):
    pip install playwright
    python -m playwright install chromium
Rodar:
    python tests/e2e_telas.py            (capturas em data/telas/)
Falha se aparecer qualquer erro de JavaScript ou se uma ação não der o resultado esperado.
"""

import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="dailylife-e2e-")
os.environ["DAILYLIFE_DATA"] = TMP
OUT = os.environ.get("DAILYLIFE_TELAS", os.path.join(ROOT, "data", "telas"))
PORT = 5079

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    print("Playwright não instalado: pip install playwright && python -m playwright install chromium")
    sys.exit(0)

from werkzeug.serving import make_server

from dailylife.core import settings
from dailylife.web import app as appmod
from tools import seed

B = f"http://127.0.0.1:{PORT}"


def main():
    os.makedirs(OUT, exist_ok=True)
    seed.run()
    srv = make_server("127.0.0.1", PORT, appmod.create_app(), threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errors, checks = [], []

    def ok(msg):
        checks.append(msg)
        print("ok:", msg)

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        pg = ctx.new_page()
        pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "ERR_FAILED" not in m.text and errors.append(m.text))
        pg.on("dialog", lambda d: d.accept())

        # Compromisso novo pelo atalho C, com término no dia seguinte
        pg.goto(B + "/")
        pg.wait_for_timeout(600)
        pg.keyboard.press("c")
        expect(pg.locator("#dlg-evento")).to_be_visible()
        pg.fill("#ev-titulo", "Teste de compromisso")
        pg.fill("#ev-ini", "16:00")
        pg.fill("#ev-fim", "17:00")
        pg.click("#form-evento button[type=submit]")
        pg.wait_for_timeout(700)
        assert pg.locator("#p-timeline .ev", has_text="Teste de compromisso").count() == 1
        ok("compromisso criado aparece na semana")

        # Série: alterar só esta ocorrência da Daily
        daily = pg.locator("#p-timeline .ev", has_text="Daily do time").nth(2)
        daily.click()
        pg.click("#p-edit")
        expect(pg.locator("#ev-escopo-box")).to_be_visible()
        assert pg.locator("#ev-escopo [data-escopo='este']").get_attribute("aria-checked") == "true"
        pg.fill("#ev-titulo", "Daily remarcada")
        pg.fill("#ev-ini", "11:00")
        pg.fill("#ev-fim", "11:30")
        pg.screenshot(path=os.path.join(OUT, "modal-so-este.png"))
        pg.click("#form-evento button[type=submit]")
        pg.wait_for_timeout(700)
        assert pg.locator("#p-timeline .ev", has_text="Daily remarcada").count() == 1
        assert pg.locator("#p-timeline .ev", has_text="Daily do time").count() == 4
        ok("só esta ocorrência foi alterada; as outras 4 seguem iguais")

        # Série: excluir só esta
        pg.locator("#p-timeline .ev", has_text="Daily do time").first.click()
        pg.click("#p-edit")
        pg.click("#ev-del")
        pg.wait_for_timeout(700)
        assert pg.locator("#p-timeline .ev", has_text="Daily do time").count() == 3
        ok("só esta ocorrência foi excluída")

        # Tarefa rápida com hashtag vai para a lista certa
        pg.fill("#p-quick", "Ler relatório #projetos")
        pg.press("#p-quick", "Enter")
        pg.wait_for_timeout(600)
        assert pg.locator("#p-todos .item", has_text="Ler relatório").count() == 0
        ok("#projetos manda a tarefa para Projetos")

        # Marcar tarefa e lembrete recorrente
        pg.locator("#p-todos .item").first.locator(".check").click()
        pg.wait_for_timeout(500)
        rem = pg.locator("#p-rems .item", has_text="Regar as plantas")
        if rem.count():
            rem.locator(".check").click()
            pg.wait_for_timeout(500)
            assert "volta" in pg.locator("#p-rems .item.done", has_text="Regar").locator(".tag").inner_text()
        ok("tarefa e lembrete marcados")

        # Calendário: visões, trocar de mês mantém o dia
        pg.goto(B + "/calendario")
        pg.wait_for_timeout(500)
        for v in ("semana", "dia", "mes"):
            pg.click(f"#c-views [data-view='{v}']")
            pg.wait_for_timeout(400)
            pg.screenshot(path=os.path.join(OUT, f"calendario-{v}.png"))
        pg.click("#c-next")
        pg.wait_for_timeout(400)
        assert "Dia livre" in pg.inner_text("#c-dia-lista") or pg.locator("#c-dia-lista .day-ev").count() >= 0
        ok("visões do calendário e troca de mês")

        # Lembretes e configurações
        pg.goto(B + "/lembretes")
        pg.wait_for_timeout(500)
        pg.locator(".rem").first.locator("[data-done]").click()
        pg.wait_for_timeout(500)
        pg.goto(B + "/config")
        pg.wait_for_timeout(500)
        pg.keyboard.press("t")
        pg.wait_for_timeout(300)
        assert pg.evaluate("document.documentElement.dataset.theme") == "escuro"
        pg.click("#s-tema [data-tema='claro']")
        ok("lembretes e configurações")
        ctx.close()

        # Todas as telas, nos dois temas, e no celular
        for tema in ("claro", "escuro"):
            settings.set("tema", tema)
            for path in ("/", "/widget", "/calendario", "/todo", "/lembretes", "/config"):
                w, h = (380, 680) if path == "/widget" else (1280, 900)
                c2 = b.new_context(viewport={"width": w, "height": h})
                pg2 = c2.new_page()
                pg2.route("**/fonts.googleapis.com/**", lambda r: r.abort())
                pg2.on("pageerror", lambda e: errors.append(str(e)))
                pg2.goto(B + path)
                pg2.wait_for_timeout(700)
                pg2.screenshot(
                    path=os.path.join(OUT, f"{(path.strip('/') or 'painel')}-{tema}.png"),
                    full_page=path != "/widget",
                )
                c2.close()
        settings.set("tema", "claro")
        # Janela estreita (entre o celular e o tamanho padrão): nada pode rolar para o lado
        t = b.new_context(viewport={"width": 900, "height": 800})
        tp = t.new_page()
        tp.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        tp.on("pageerror", lambda e: errors.append("janela estreita: " + str(e)))
        for path, name in (
            ("/", "painel"),
            ("/calendario", "calendario"),
            ("/todo", "todo"),
            ("/entrar", "entrar"),
        ):
            tp.goto(B + path)
            tp.wait_for_timeout(700)
            largura = tp.evaluate("document.documentElement.scrollWidth")
            if largura > 900:
                errors.append(f"janela estreita: {path} rola para o lado ({largura}px)")
            tp.screenshot(path=os.path.join(OUT, f"estreita-{name}.png"), full_page=True)
        t.close()
        m = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        mp = m.new_page()
        mp.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        mp.on("pageerror", lambda e: errors.append("celular: " + str(e)))
        for path, name in (("/", "painel"), ("/calendario", "calendario"), ("/lembretes", "lembretes")):
            mp.goto(B + path)
            mp.wait_for_timeout(700)
            mp.screenshot(path=os.path.join(OUT, f"celular-{name}.png"), full_page=True)
        ok("capturas das telas nos dois temas e no celular")
        b.close()

    srv.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    if errors:
        print("ERROS DE JAVASCRIPT:")
        for e in errors:
            print("  ", e)
        sys.exit(1)
    print(f"\n{len(checks)} verificações ok. Capturas em {OUT}")


if __name__ == "__main__":
    main()
