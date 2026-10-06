# Snep Pizzaria — Site de Delivery

Site de pedidos no estilo do delivery da Norbas Pizzaria (`norbas.com.br`), feito em
Flask + SQLAlchemy, preparado para multi-tenant (várias pizzarias na mesma
instalação, cada uma com sua própria URL `/<slug>/`).

Pagamento é sempre na entrega (Dinheiro, Pix, Débito, Crédito) — não há
checkout online. O pedido finalizado gera uma mensagem pronta e abre o
WhatsApp da loja com tudo preenchido.

## Como rodar localmente

```bash
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt

copy .env.example .env       # e ajuste se quiser usar Postgres local
python seed.py data/snep/cardapio.json   # cria o banco (sqlite por padrão) e importa o cardápio
python run.py
```

Acesse `http://localhost:5000/snep/`.

## Prévia sem servidor (para mandar ao cliente)

```bash
python build_static_preview.py        # gera snep-pizzaria-previa.html (imagens embutidas)
```

Usa exatamente o mesmo template/CSS/JS do site, então o que o cliente vê na
prévia é o que vai para o ar.

## Estrutura

```
app/
  models.py              -> Tenant, Category, Product, ProductVariant, Addon, Border,
                             Neighborhood, Customer, Order, OrderItem
  routes/public.py       -> página do cardápio (layout Norbas), lê imagens de static/img/<slug>/
  routes/orders.py       -> POST /<slug>/api/pedido: calcula taxa, grava o pedido, devolve link wa.me
  services/menu_data.py  -> monta o JSON do cardápio (do banco ou do cardapio.json)
  services/delivery.py   -> taxa de entrega por bairro
  services/whatsapp.py   -> mensagem do pedido e link wa.me
  templates/index.html   -> página única (cardápio + fluxo de sabores/borda/adicionais + cesta + checkout)
  static/css/delivery.css, static/js/delivery.js
  static/img/snep/       -> logo.webp, banner1.webp, banner2.webp, fundo.webp
data/snep/cardapio.json  -> cardápio, bairros, horários (fonte de verdade)
seed.py                  -> importa o cardapio.json para o banco
build_static_preview.py  -> gera o HTML único de prévia
```

## Visual

Reprodução do delivery da Norbas (norbas.com.br/delivery): cabeçalho vermelho
com logo quadrada, carrossel de banners, barra Aberto/Fechado + tempo de
entrega + formas de pagamento, busca/filtro, categorias com cards "A partir
de R$" e botões "1 sabor / 2 sabores", modal em etapas (sabores → borda →
adicionais → confirmação), cesta lateral (barra inferior no celular).
O pedido vai para o WhatsApp da loja e fica gravado na tabela `orders`.

## Status do cardápio e regras de negócio

- **68 bairros de Itu com taxa de entrega** já cadastrados em
  `data/snep/cardapio.json` (`neighborhoods`), de R$ 4,00 a R$ 18,00.
  Se um bairro digitado no checkout não estiver na lista, o site mostra
  "Entrega: a confirmar" e o valor é combinado pela loja no WhatsApp.
- **Pizza Metro** (combo de R$ 169,99, até 4 sabores à escolha entre as linhas
  Promocional e Premium, preço fixo independente dos sabores) já está
  modelada como categoria própria, com os 4 seletores de sabor na página do
  produto.
- **Meio a meio cobra o sabor mais caro** — implementado, só permite
  combinar sabores dentro da mesma linha (Promocional com Promocional,
  Premium com Premium, Doce com Doce).
- **Fotos** dos produtos/banner ainda não foram enviadas — o layout já tem
  os espaços prontos (`store-banner` no cabeçalho; um `image_url` pode ser
  adicionado ao `Product` facilmente quando as fotos chegarem).

## Deploy no Fly.io (região gru / São Paulo)

```bash
fly launch --no-deploy        # usa o fly.toml já incluso
fly postgres create           # cria um Postgres gerenciado
fly postgres attach <nome-do-banco>   # injeta DATABASE_URL automaticamente
fly deploy
fly ssh console -C "python seed.py data/snep/cardapio.json"   # popula o banco em produção
```

## Adicionando uma nova pizzaria (multi-tenant)

Crie `data/<slug>/cardapio.json` seguindo o mesmo formato de
`data/snep/cardapio.json` e rode `python seed.py data/<slug>/cardapio.json`.
A loja fica disponível em `/<slug>/` automaticamente — nenhuma mudança de
código é necessária.
