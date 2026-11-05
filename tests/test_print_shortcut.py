"""Atalho do painel para imprimir direto: abre o navegador com --kiosk-printing num perfil só dele."""
from tests.test_admin import admin, panel  # noqa: F401


def test_shortcut_opens_this_store_panel_with_direct_printing(panel):
    r = panel.get("/snep/admin/loja/atalho-impressao", headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 200
    assert "attachment" in r.headers["Content-Disposition"] and ".cmd" in r.headers["Content-Disposition"]
    body = r.get_data(as_text=True)
    assert 'set "PAINEL=https://localhost/snep/admin/pedidos"' in body
    assert "--kiosk-printing" in body and '--user-data-dir="%PERFIL%"' in body
    assert "PainelLoja-snep" in body
    assert "\r\n" in body and "\n" not in body.replace("\r\n", "")  # o Windows exige fim de linha CRLF


def test_shortcut_needs_login(client):
    assert client.get("/snep/admin/loja/atalho-impressao").status_code == 302


def test_store_page_offers_the_shortcut(panel):
    assert "/admin/loja/atalho-impressao" in panel.get("/snep/admin/loja").get_data(as_text=True)
