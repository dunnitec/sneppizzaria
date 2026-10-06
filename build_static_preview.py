"""Gera um HTML único (sem servidor) usando o MESMO template/CSS/JS do site Flask,
com imagens embutidas — para mandar como prévia ao cliente.

Uso: python build_static_preview.py [data/<slug>/cardapio.json] [saida.html]
Imagens em app/static/img/<slug>/: logo.webp, banner*.webp, fundo.webp (opcionais)
"""
import base64
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from app.services.menu_data import PAY_ICONS, data_from_json

ROOT = Path(__file__).parent
src = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data/snep/cardapio.json")
cardapio = json.loads(src.read_text(encoding="utf-8"))
slug = cardapio["tenant"]["slug"]
out = Path(sys.argv[2] if len(sys.argv) > 2 else ROOT / f"{slug}-pizzaria-previa.html")

IMG = ROOT / "app/static/img" / slug


def data_uri(p):
    return "data:image/webp;base64," + base64.b64encode(p.read_bytes()).decode()


assets = {
    "logo": data_uri(IMG / "logo.webp") if (IMG / "logo.webp").exists() else "",
    "banners": [data_uri(p) for p in sorted(IMG.glob("banner*.webp"))],
    "fundo": data_uri(IMG / "fundo.webp") if (IMG / "fundo.webp").exists() else "",
}

d = data_from_json(cardapio, order_url="__static__", assets=assets)

env = Environment(loader=FileSystemLoader(ROOT / "app/templates"), autoescape=True)
env.filters["tojson"] = lambda v: Markup(json.dumps(v, ensure_ascii=False).replace("<", "\\u003c"))
tpl = env.get_template("index.html")

css = (ROOT / "app/static/css/delivery.css").read_text(encoding="utf-8")
js = (ROOT / "app/static/js/delivery.js").read_text(encoding="utf-8")
# na prévia não há servidor: monta o link do WhatsApp direto no navegador
js += r"""
window.__staticFinish = function(payload){
  const money=v=>"R$ "+v.toFixed(2).replace(".",",");
  const s=payload.items.reduce((a,i)=>a+i.unit_price*i.quantity,0);
  const n=DATA.neighborhoods.find(x=>x.name===payload.neighborhood);
  const fee=payload.withdraw?0:(n?n.fee:null), t=s+(fee||0);
  let L=[`*Novo pedido - ${DATA.tenant.name}*`,""];
  payload.items.forEach(i=>{L.push(`▪ ${i.quantity}x ${i.title} (${i.variant})`);if(i.border)L.push(`   Borda: ${i.border}`);if(i.addons)L.push(`   Adicionais: ${i.addons}`);if(i.notes)L.push(`   Obs: ${i.notes}`);L.push(`   ${money(i.unit_price*i.quantity)}`);});
  L.push("",`Subtotal: ${money(s)}`);
  if(payload.withdraw)L.push("Retirada na loja",`*Total: ${money(t)}*`);else if(fee!==null)L.push(`Entrega: ${money(fee)}`,`*Total: ${money(t)}*`);else L.push("Entrega: a confirmar",`*Total (sem entrega): ${money(t)}*`);
  L.push("",`*Cliente:* ${payload.customer_name}`,`*Telefone:* ${payload.customer_phone}`);
  if(!payload.withdraw){L.push(`*Endereço:* ${payload.street}, ${payload.number} - ${payload.neighborhood||"(outro bairro)"}`);if(payload.complement)L.push(`Complemento: ${payload.complement}`);if(payload.reference)L.push(`Referência: ${payload.reference}`);}
  L.push(`*Pagamento:* ${payload.payment_method}`);if(payload.payment_method==="Dinheiro"&&payload.change_for)L.push(`Troco para: ${money(parseFloat(payload.change_for))}`);
  return {ok:true,wa_link:"https://wa.me/"+DATA.tenant.whatsapp+"?text="+encodeURIComponent(L.join("\n"))};
};
const __fetch=window.fetch;
window.fetch=function(url,opt){ if(url==="__static__") return Promise.resolve({json:()=>Promise.resolve(window.__staticFinish(JSON.parse(opt.body)))}); return __fetch.apply(this,arguments); };
"""

html = tpl.render(d=d, pay_icons=PAY_ICONS, inline=True, css=css, js=js)
out.write_text(html, encoding="utf-8")
print(f"Gerado: {out} ({out.stat().st_size // 1024} KB)")
