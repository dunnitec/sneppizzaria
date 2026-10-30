"""Como o site do cliente aparece e funciona, escolhido pelo dono em Aparência → “Como o site funciona”.

Fica num JSON em Tenant.site_options; o que não foi escolhido usa o padrão (DEFAULTS), então uma
opção nova já nasce com o comportamento de antes para todas as lojas.
"""
import json
import re

DEFAULT_COLOR = "#e3141b"
DEFAULTS = {
    "show_filter": True,  # caixa “Filtrar cardápio” acima das categorias
    "flavors_one_page": True,  # pizza de 2+ sabores: todos marcados numa tela só (False = um sabor por tela)
    "borders_grouped": True,  # bordas separadas por tipo (Tradicional, Caracol, Vulcão), abrindo ao tocar
    "layout": "grade",  # grade (2 por linha no computador) | lista (1 por linha)
    "color": DEFAULT_COLOR,  # cor principal (botões, destaques)
    "theme": "escuro",  # escuro | claro (fundo do site)
    "font": "montserrat",  # fonte do nome da pizzaria no topo (FONTS)
    "show_infobar": True,  # barra “aberto/fechado · entrega · pagamento” embaixo dos banners
    "flavor_photos": True,  # foto de cada sabor na lista de escolher sabores
}
LAYOUTS = ("grade", "lista")
THEMES = ("escuro", "claro")
# fonte do nome: rótulo no painel, nome no CSS e parâmetro do Google Fonts (None = já carregada pelo site)
FONTS = {
    "montserrat": ("Montserrat (padrão)", '"Montserrat"', None),
    "bebas": ("Bebas Neue", '"Bebas Neue"', "Bebas+Neue"),
    "oswald": ("Oswald", '"Oswald"', "Oswald:wght@700"),
    "anton": ("Anton", '"Anton"', "Anton"),
    "lobster": ("Lobster", '"Lobster"', "Lobster"),
    "pacifico": ("Pacifico", '"Pacifico"', "Pacifico"),
    "playfair": ("Playfair Display", '"Playfair Display"', "Playfair+Display:wght@900"),
}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def options(tenant):
    try:
        saved = json.loads(tenant.site_options) if tenant.site_options else {}
    except ValueError:
        saved = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in saved.items() if k in DEFAULTS})
    if out["layout"] not in LAYOUTS:
        out["layout"] = DEFAULTS["layout"]
    if out["theme"] not in THEMES:
        out["theme"] = DEFAULTS["theme"]
    if out["font"] not in FONTS:
        out["font"] = DEFAULTS["font"]
    if not HEX.match(str(out["color"])):
        out["color"] = DEFAULT_COLOR
    return out


def from_form(form):
    """Lê o formulário do painel; caixas desmarcadas não vêm no formulário (= False)."""
    color = (form.get("color") or "").strip()
    return {
        "show_filter": "show_filter" in form,
        "flavors_one_page": form.get("flavors") != "steps",
        "borders_grouped": "borders_grouped" in form,
        "layout": form.get("layout") if form.get("layout") in LAYOUTS else DEFAULTS["layout"],
        "color": color.lower() if HEX.match(color) else DEFAULT_COLOR,
        "theme": form.get("theme") if form.get("theme") in THEMES else DEFAULTS["theme"],
        "font": form.get("font") if form.get("font") in FONTS else DEFAULTS["font"],
        "show_infobar": "show_infobar" in form,
        "flavor_photos": "flavor_photos" in form,
    }


def _mix(hex_color, other, amount):
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def color_css(opts):
    """CSS da cor principal e da fonte do nome (por cima de static/css/delivery.css); '' = tudo padrão."""
    css, c = "", opts["color"]
    if c != DEFAULT_COLOR:
        css += f":root{{--red:{c};--red-2:{_mix(c, '#000000', .3)};--red-soft:{_mix(c, '#ffffff', .2)}}}"
    if opts["font"] != DEFAULTS["font"]:
        css += f".brand-name{{font-family:{FONTS[opts['font']][1]},var(--display)}}"
    return css


def font_url(opts):
    """Google Fonts da fonte escolhida para o nome; '' = a padrão (já carregada)."""
    family = FONTS[opts["font"]][2]
    return f"https://fonts.googleapis.com/css2?family={family}&display=swap" if family else ""
