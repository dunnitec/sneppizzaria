"""Vídeo "como pedir": só aparece onde HOWTO_VIDEO está configurado (a Snep), não nas outras instalações."""


def test_no_video_button_by_default(client, tenant):
    html = client.get("/snep/").get_data(as_text=True)
    assert "howtoOpen" not in html and "<video" not in html


def test_video_button_when_configured(app, client, tenant):
    app.config["HOWTO_VIDEO"] = "como-pedir-1.mp4"
    html = client.get("/snep/").get_data(as_text=True)
    assert "Primeira vez aqui?" in html and 'src="/uploads/como-pedir-1.mp4"' in html
    assert 'preload="none"' in html  # não gasta a internet de quem não abre o vídeo
