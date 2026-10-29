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
}
LAYOUTS = ("grade", "lista")
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
    }


def _mix(hex_color, other, amount):
    a = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def color_css(opts):
    """Variáveis de cor do site (static/css/delivery.css) a partir da cor principal; '' = cor padrão."""
    c = opts["color"]
    if c == DEFAULT_COLOR:
        return ""
    return f":root{{--red:{c};--red-2:{_mix(c, '#000000', .3)};--red-soft:{_mix(c, '#ffffff', .2)}}}"
