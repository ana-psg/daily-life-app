"""Testes da Fase 4 da versão 2: acesso pelo celular com Tailscale, senha, QR code e Web Push.

Rodar: python -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_app  # noqa: F401  (prepara o banco temporário)
from test_app import reset

from dailylife import push, qr, tailscale
from dailylife.core import ValidationError, settings
from dailylife.desktop import notifier
from dailylife.web import app as appmod

TS = "notebook.tail1234.ts.net"


def ts_outputs(state="Running", serving=True):
    """Respostas falsas do comando tailscale (status e serve status)."""
    status = {
        "BackendState": state,
        "Self": {"DNSName": TS + ".", "TailscaleIPs": ["100.101.102.103", "fd7a::1"]},
    }
    serve = {"Web": {f"{TS}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:5055"}}}}} if serving else {}

    def run(*args, timeout=20):
        if args[:2] == ("status", "--json"):
            return 0, json.dumps(status)
        if args[:3] == ("serve", "status", "--json"):
            return 0, json.dumps(serve)
        return 0, ""

    return run


class TailscaleTests(unittest.TestCase):
    def test_status_le_nome_ip_e_endereco_publicado(self):
        with (
            mock.patch.object(tailscale, "find_cli", return_value="tailscale"),
            mock.patch.object(tailscale, "_run", ts_outputs()),
        ):
            st = tailscale.status()
        self.assertEqual((st["nome"], st["ip"]), (TS, "100.101.102.103"))
        self.assertTrue(st["conectado"] and st["publicado"])
        self.assertEqual(tailscale.address(st), f"https://{TS}")

    def test_sem_tailscale_instalado(self):
        with mock.patch.object(tailscale, "find_cli", return_value=None):
            st = tailscale.status()
        self.assertFalse(st["instalado"] or st["conectado"])

    def test_https_nao_liberado_devolve_o_link(self):
        text = "Serve is not enabled on your tailnet.\nTo enable, visit:\n\n  https://login.tailscale.com/f/serve?node=abc123\n"
        with mock.patch.object(tailscale, "_run", return_value=(124, text)):
            r = tailscale.publish()
        self.assertFalse(r["ok"])
        self.assertEqual(r["link"], "https://login.tailscale.com/f/serve?node=abc123")

    def test_serve_de_outra_porta_nao_conta(self):
        other = {"Web": {f"{TS}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8080"}}}}}
        self.assertFalse(tailscale._serving(other))


class RemoteAccessTests(unittest.TestCase):
    def setUp(self):
        reset()
        appmod._login_fails.clear()
        self.c = appmod.create_app().test_client()

    def test_pedido_pelo_tailscale_conta_como_de_fora(self):
        # O `tailscale serve` conecta de 127.0.0.1, mas com o endereço *.ts.net no Host
        ts = {"Host": TS}
        self.assertEqual(self.c.get("/api/painel", headers=ts).status_code, 403)  # acesso desligado
        settings.set("acesso_rede", True)
        settings.set_password("segredo123")
        self.assertEqual(self.c.get("/api/painel", headers=ts).status_code, 401)
        self.assertEqual(self.c.post("/api/celular/ligar", headers=ts).status_code, 403)
        self.c.post("/entrar", data={"senha": "segredo123"}, headers=ts)
        self.assertEqual(self.c.get("/api/painel", headers=ts).status_code, 200)
        self.assertEqual(
            self.c.post("/api/config/senha", json={"senha": "outra1234"}, headers=ts).status_code, 403
        )

    def test_cabecalho_do_tailscale_tambem_conta_como_de_fora(self):
        settings.set("acesso_rede", True)
        settings.set_password("segredo123")
        r = self.c.get("/api/painel", headers={"Tailscale-User-Login": "pessoa@example.com"})
        self.assertEqual(r.status_code, 401)

    def test_tailscale_que_troca_o_host_tambem_conta_como_de_fora(self):
        # Se o `tailscale serve` mandar Host 127.0.0.1, o endereço original vem em X-Forwarded-Host
        settings.set("acesso_rede", True)
        settings.set_password("segredo123")
        proxy = {"Host": "127.0.0.1:5055", "X-Forwarded-Host": TS, "X-Forwarded-For": "100.64.0.5"}
        self.assertEqual(self.c.get("/api/painel", headers=proxy).status_code, 401)
        self.c.post("/entrar", data={"senha": "segredo123"}, headers={**proxy, "Origin": f"https://{TS}"})
        r = self.c.post(
            "/api/todos", json={"titulo": "Do celular"}, headers={**proxy, "Origin": f"https://{TS}"}
        )
        self.assertEqual(r.status_code, 201)
        r = self.c.post(
            "/api/todos", json={"titulo": "x"}, headers={**proxy, "Origin": "https://site-ruim.example"}
        )
        self.assertEqual(r.status_code, 403)

    def test_no_computador_continua_sem_senha(self):
        settings.set_password("segredo123")
        self.assertEqual(self.c.get("/api/painel").status_code, 200)

    def test_ligar_exige_senha_e_tailscale_conectado(self):
        with (
            mock.patch.object(tailscale, "find_cli", return_value="tailscale"),
            mock.patch.object(tailscale, "_run", ts_outputs(serving=False)),
        ):
            self.assertEqual(self.c.post("/api/celular/ligar").status_code, 400)
            settings.set_password("segredo123")
            with mock.patch.object(tailscale, "publish", return_value={"ok": True}):
                r = self.c.post("/api/celular/ligar").get_json()
            self.assertTrue(r["ok"] and r["acesso"])
            r = self.c.post("/api/celular/desligar").get_json()
            self.assertFalse(r["acesso"])
        with (
            mock.patch.object(tailscale, "find_cli", return_value="tailscale"),
            mock.patch.object(tailscale, "_run", ts_outputs(state="Stopped")),
        ):
            r = self.c.post("/api/celular/ligar")
            self.assertEqual(r.status_code, 400)
            self.assertIn("Tailscale", r.get_json()["erro"])

    def test_tela_mostra_qr_quando_ligado(self):
        settings.set("acesso_rede", True)
        with (
            mock.patch.object(tailscale, "find_cli", return_value="tailscale"),
            mock.patch.object(tailscale, "_run", ts_outputs()),
        ):
            c = self.c.get("/api/celular").get_json()
        self.assertEqual(c["endereco"], f"https://{TS}")
        self.assertTrue(c["qr"].startswith("<svg"))


class ServerBindTests(unittest.TestCase):
    def test_servidor_escuta_so_neste_pc(self):
        import socket

        from dailylife import config
        from dailylife.desktop import app as desktop

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        settings.set("acesso_rede", True)  # mesmo com o acesso ligado, nada de rede de casa
        with mock.patch.object(config, "PORT", port):
            server = desktop.ServerThread(appmod.create_app())
        try:
            self.assertEqual(server.server.server_address[0], "127.0.0.1")
        finally:
            server.server.server_close()


class PasswordTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_senha_curta_e_recusada(self):
        with self.assertRaises(ValidationError):
            settings.set_password("12345")
        settings.set_password("abc123")
        self.assertTrue(settings.check_password("abc123"))
        self.assertFalse(settings.check_password("abc124"))

    def test_pin_antigo_continua_valendo(self):
        settings.set("pin_hash", settings._hash_password("2468", os.urandom(16)))
        self.assertTrue(settings.check_password("2468"))


class QrTests(unittest.TestCase):
    def test_tamanho_cresce_com_o_texto(self):
        self.assertEqual(len(qr.matrix("a")), 21)  # versão 1
        self.assertEqual(len(qr.matrix(f"https://{TS}")), 29)  # versão 3
        with self.assertRaises(ValueError):
            qr.matrix("x" * 400)

    def test_camera_le_o_qr_code(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("OpenCV não instalado")
        for text in ("a", f"https://{TS}", "https://" + "x" * 150):
            grid = qr.matrix(text)
            n, s = len(grid) + 8, 8
            img = np.full((n * s, n * s), 255, np.uint8)
            for y, row in enumerate(grid):
                for x, cell in enumerate(row):
                    if cell:
                        img[(y + 4) * s : (y + 5) * s, (x + 4) * s : (x + 5) * s] = 0
            # Dois leitores do OpenCV: o clássico às vezes não acha o código, o Aruco é mais tolerante
            found = (
                cv2.QRCodeDetector().detectAndDecode(img)[0]
                or cv2.QRCodeDetectorAruco().detectAndDecode(img)[0]
            )
            self.assertEqual(found, text)


@unittest.skipUnless(push.AVAILABLE, "cryptography não instalada")
class PushTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_cifragem_igual_ao_exemplo_do_rfc_8291(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        u = push.unb64
        key = ec.derive_private_key(
            int.from_bytes(u("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1()
        )
        out = push.encrypt(
            u("V2hlbiBJIGdyb3cgdXAsIEkgd2FudCB0byBiZSBhIHdhdGVybWVsb24"),
            u("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"),
            u("BTBZMqHH6r4Tts7J_aSIgg"),
            server_key=key,
            salt=u("DGv6ra1nlYgDCS1FRnbzlw"),
        )
        expected = (
            "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
            "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
            "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
        )
        self.assertEqual(push.b64(out), expected)

    def test_assinatura_vapid_confere(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

        header = push.vapid_header("https://fcm.googleapis.com/fcm/send/abc")
        token = header.split("t=")[1].split(",")[0]
        k = header.split("k=")[1]
        head, body, sig = token.split(".")
        claims = json.loads(push.unb64(body))
        self.assertEqual(claims["aud"], "https://fcm.googleapis.com")
        self.assertEqual(k, push.public_key())
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), push.unb64(k))
        raw = push.unb64(sig)
        der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
        pub.verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))  # erro se não conferir

    def _subscription(self, endpoint="https://fcm.googleapis.com/fcm/send/abc"):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        browser = ec.generate_private_key(ec.SECP256R1())
        p256dh = browser.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return {"endpoint": endpoint, "keys": {"p256dh": push.b64(p256dh), "auth": push.b64(os.urandom(16))}}

    def test_inscricao_invalida_e_recusada(self):
        with self.assertRaises(ValidationError):
            push.subscribe({"endpoint": "http://inseguro", "keys": {}})
        with self.assertRaises(ValidationError):
            push.subscribe({"endpoint": "https://x", "keys": {"p256dh": "abc", "auth": "def"}})

    def test_envio_e_inscricao_vencida_sai(self):
        push.subscribe(self._subscription("https://push.example/ok"))
        push.subscribe(self._subscription("https://push.example/vencida"))
        sent_to = []

        class Resp:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=15):
            sent_to.append(req.full_url)
            self.assertEqual(req.headers["Content-encoding"], "aes128gcm")
            self.assertTrue(req.headers["Authorization"].startswith("vapid t="))
            if req.full_url.endswith("vencida"):
                raise urllib.error.HTTPError(req.full_url, 410, "Gone", {}, None)
            return Resp()

        with mock.patch.object(push.urllib.request, "urlopen", fake_urlopen):
            self.assertEqual(push.send_all({"titulo": "Oi"}), 1)
        self.assertEqual(len(sent_to), 2)
        self.assertEqual([d["endpoint"] for d in push.devices()], ["https://push.example/ok"])

    def test_api_inscreve_e_cancela(self):
        c = appmod.create_app().test_client()
        sub = self._subscription()
        self.assertEqual(c.post("/api/push/inscrever", json={"inscricao": sub}).status_code, 200)
        self.assertEqual(c.get("/api/celular").get_json()["push"]["aparelhos"], 1)
        c.post("/api/push/cancelar", json={"endpoint": sub["endpoint"]})
        self.assertEqual(push.devices(), [])


class NotifierPushTests(unittest.TestCase):
    def test_aviso_vai_para_o_celular_so_quando_os_avisos_estao_ligados(self):
        with mock.patch.object(push, "send_async") as send, mock.patch.object(notifier, "TOAST_OK", False):
            notifier.notify("Água", "Agora", kind="lembrete", ref_id=7)
            notifier.notify("Só no app", nativo=False)
        self.assertEqual(send.call_count, 1)
        msg = send.call_args[0][0]
        self.assertEqual((msg["tipo"], msg["id"], msg["url"]), ("lembrete", 7, "/lembretes"))


if __name__ == "__main__":
    unittest.main()
