/* Painel → Novo pedido: monta os itens com as mesmas regras do site e envia para o servidor,
   que recalcula os preços. O total aqui é só uma prévia. */
(function () {
  "use strict";
  const D = window.POS_DATA;
  const form = document.getElementById("pos");
  const $ = (sel) => form.querySelector(sel);
  const money = (v) => "R$ " + Number(v).toFixed(2).replace(".", ",");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const token = document.querySelector('meta[name="csrf-token"]').content;
  const cart = [];
  const SMALL_PIZZA = /broto|pequen|mini|individual|meia/i; // adicional com preço de pequena (igual ao servidor)
  let B = null; // item sendo montado: {cat, size, n, flavors[], border, addons{}, choice, qty, notes}

  /* ---------- origem do pedido ---------- */
  const channel = () => form.querySelector('[name="channel"]:checked').value;
  const delivery = () => channel() === "telefone" && $("#pos-delivery").checked;
  function applyChannel() {
    form.querySelectorAll("[data-for]").forEach((el) => { el.hidden = !el.dataset.for.split(" ").includes(channel()); });
    $("#pos-address").hidden = !delivery();
    if ($("#pos-other")) $("#pos-other").hidden = !other();
    renderTotal();
  }
  form.querySelectorAll('[name="channel"]').forEach((r) => r.addEventListener("change", applyChannel));
  $("#pos-delivery").addEventListener("change", applyChannel);
  const other = () => delivery() && $('[name="neighborhood"]').value === "__outro__";
  // valor digitado: "1.234,50", "20,5" ou "20.50"; vazio = null
  const num = (v) => { v = String(v || "").trim(); return v === "" ? null : Number(v.includes(",") ? v.replace(/\./g, "").replace(",", ".") : v); };
  $('[name="neighborhood"]').addEventListener("change", () => { if ($("#pos-other")) $("#pos-other").hidden = !other(); renderTotal(); });
  $('[name="delivery_fee"]').addEventListener("input", renderTotal);
  /* ---------- casa, apartamento ou condomínio: acréscimo na entrega (painel → Entrega) ---------- */
  let quoted = null;  // taxa da distância calculada; o campo da taxa soma o acréscimo do tipo de endereço
  const resFee = () => (D.residence_fees || {})[form.residence.value] || 0;
  form.residence.addEventListener("change", () => {
    $("#pos-building").hidden = form.residence.value === "casa";
    if (D.km && quoted !== null) $("#pos-km-fee").value = (quoted + resFee()).toFixed(2).replace(".", ",");
    renderTotal();
  });
  /* ---------- frete por distância: CEP → rua, bairro e taxa sugerida (editável) ---------- */
  const km = (v) => Number(v).toFixed(1).replace(".", ",");
  async function kmQuote() {
    const cepEl = $('[name="cep"]'), info = $("#pos-km-info");
    const cep = cepEl.value.replace(/\D/g, "");
    if (cep.length !== 8 && !$('[name="street"]').value.trim()) return;
    info.textContent = "Calculando…";
    quoted = null;
    try {
      const qs = new URLSearchParams({ cep, street: $('[name="street"]').value.trim(), neighborhood: $('[name="neighborhood"]').value.trim() });
      const r = await (await fetch(cepEl.dataset.url + "?" + qs, { credentials: "same-origin" })).json();
      if (r.street && !$('[name="street"]').value) $('[name="street"]').value = r.street;
      if (r.neighborhood && !$('[name="neighborhood"]').value) $('[name="neighborhood"]').value = r.neighborhood;
      const feeEl = $("#pos-km-fee");
      if (r.status === "ok") { quoted = r.fee; feeEl.value = (r.fee + resFee()).toFixed(2).replace(".", ","); info.textContent = `${km(r.km)} km · taxa ${money(r.fee)}${resFee() ? ` + ${money(resFee())} do tipo de endereço` : ""} (pode mudar o valor).`; }
      else if (r.status === "far") { feeEl.value = ""; info.textContent = `Fica a cerca de ${km(r.km)} km, fora da área de entrega (até ${km(D.km.max)} km). Para entregar mesmo assim, digite a taxa.`; }
      else if (r.status === "store") { feeEl.value = ""; info.textContent = "A pizzaria ainda não está no mapa (aba Entrega). Digite a taxa."; }
      else { feeEl.value = ""; info.textContent = cep.length === 8 && !r.cep_found ? "CEP não encontrado. Preencha rua e bairro e digite a taxa." : "Endereço não achado no mapa. Combine e digite a taxa."; }
    } catch (e) { info.textContent = "Sem conexão para calcular. Digite a taxa."; }
    renderTotal();
  }
  if (D.km) {
    $('[name="cep"]').addEventListener("input", (e) => {
      const d = e.target.value.replace(/\D/g, "").slice(0, 8);
      e.target.value = d.length > 5 ? d.slice(0, 5) + "-" + d.slice(5) : d;
      if (d.length === 8) { $('[name="street"]').value = ""; $('[name="neighborhood"]').value = ""; kmQuote(); }
    });
    $('[name="street"]').addEventListener("change", () => { if (!$('[name="cep"]').value) kmQuote(); });
  }
  $('[name="payment_method"]').addEventListener("change", (e) => { $("#pos-change").hidden = e.target.value !== "Dinheiro"; });
  $('[name="split_people"]').addEventListener("change", renderTotal);

  /* ---------- regras (as mesmas do site) ---------- */
  const comboOf = (c) => Object.assign({ sources: [], extras: [], choice_label: "", choice_options: [] }, c.combo || {});
  const isCombo = () => B.cat.kind === "metro";
  const sizesOf = (c) => [...new Set(c.products.flatMap((p) => p.variants.map((v) => v.label)))];
  const maxFlavors = (c, label) => Math.max(1, ...c.products.map((p) => (p.variants.find((v) => v.label === label) || {}).max_flavors || 1));
  function flavorPool() {
    if (isCombo()) {
      const src = comboOf(B.cat).sources;
      return D.categories.filter((c) => c.kind !== "metro" && c.kind !== "bebida" && src.includes(c.slug))
        .flatMap((c) => c.products.map((p) => ({ id: p.id, name: p.name, price: null })));
    }
    return B.cat.products.map((p) => { const v = p.variants.find((x) => x.label === B.size); return v ? { id: p.id, name: p.name, price: v.price, promo: v.promo, no_border: p.no_border } : null; }).filter(Boolean);
  }
  const borderOptions = () => B.flavors.some((f) => f && f.no_border) ? [] : D.borders.filter((b) => !(b.no_sizes || []).includes(B.size) && !(b.no_categories || []).includes(B.cat.slug));
  function unitPrice() {
    if (isCombo()) return B.cat.products[0].variants[0].price;
    const chosen = B.flavors.filter(Boolean);
    if (!chosen.length) return 0;
    let p = Math.max(...chosen.map((f) => f.price));
    const border = D.borders.find((b) => b.id === B.border);
    if (border) p += border.price;
    const whole = !SMALL_PIZZA.test(B.size);
    Object.entries(B.addons).forEach(([id, q]) => { const a = D.addons.find((x) => x.id === Number(id)); if (a) p += q * (whole ? a.price_whole : a.price_half); });
    return p;
  }

  /* ---------- montar item ---------- */
  const catsBox = $("#pos-cats"), builder = $("#pos-builder");
  D.categories.forEach((c, ci) => {
    catsBox.insertAdjacentHTML("beforeend", `<button type="button" class="chip-btn" data-ci="${ci}">${esc(c.name)}</button>`);
  });
  catsBox.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-ci]");
    if (!btn) return;
    catsBox.querySelectorAll(".chip-btn").forEach((b) => b.classList.toggle("on", b === btn));
    const cat = D.categories[Number(btn.dataset.ci)];
    if (cat.kind === "bebida") { B = { cat }; renderDrinks(); return; }
    const size = cat.kind === "metro" ? cat.products[0].variants[0].label : sizesOf(cat)[0];
    B = { cat, size, n: 1, flavors: [], border: null, addons: {}, choice: "", qty: 1, notes: "" };
    renderBuilder();
  });

  function renderDrinks() {
    builder.hidden = false;
    builder.innerHTML = `<h3>${esc(B.cat.name)}</h3><p class="hint">Toque no tamanho para adicionar.</p>` + B.cat.products.map((p) =>
      `<div class="drink-row"><b>${esc(p.name)}</b>${p.variants.map((v) => `<button type="button" class="ghost small" data-drink="${p.id}" data-size="${esc(v.label)}">${esc(v.label)} · ${money(v.price)}${v.promo ? " 🏷" : ""}</button>`).join("")}</div>`).join("");
  }
  builder.addEventListener("click", (e) => {
    const d = e.target.closest("[data-drink]");
    if (!d) return;
    const p = B.cat.products.find((x) => x.id === Number(d.dataset.drink));
    const v = p.variants.find((x) => x.label === d.dataset.size);
    const same = cart.find((i) => i.sel.flavors[0] === p.id && i.sel.variant === v.label);
    if (same) same.qty++; else cart.push({ sel: { category_id: B.cat.id, variant: v.label, flavors: [p.id] }, title: p.name, detail: v.label, price: v.price, qty: 1 });
    renderCart();
  });

  function renderBuilder() {
    builder.hidden = false;
    const combo = isCombo(), max = combo ? B.cat.products[0].variants[0].max_flavors : maxFlavors(B.cat, B.size);
    if (B.n > max) B.n = max;
    const pool = flavorPool();
    let html = `<h3>${esc(B.cat.name)}</h3>`;
    if (!combo) html += `<div class="row"><span class="where-label">Tamanho</span>${sizesOf(B.cat).map((s) => `<button type="button" class="chip-btn ${s === B.size ? "on" : ""}" data-size-pick="${esc(s)}">${esc(s)}</button>`).join("")}</div>`;
    html += `<div class="row"><span class="where-label">Sabores</span>${Array.from({ length: max }, (_, i) => `<button type="button" class="chip-btn ${i + 1 === B.n ? "on" : ""}" data-n="${i + 1}">${i + 1}</button>`).join("")}</div>`;
    for (let i = 0; i < B.n; i++) {
      html += `<label class="grow">${B.n > 1 ? `${i + 1}º sabor` : "Sabor"}<select data-flavor="${i}"><option value="">Escolha…</option>${pool.map((f) => `<option value="${f.id}" ${B.flavors[i] && B.flavors[i].id === f.id ? "selected" : ""}>${esc(f.name)}${f.price != null ? ` — ${money(f.price)}` : ""}${f.promo ? " 🏷 promoção" : ""}</option>`).join("")}</select></label>`;
    }
    const borders = combo ? [] : borderOptions();
    if (borders.length) html += `<label class="grow">Borda<select data-border><option value="">Sem borda</option>${borders.map((b) => `<option value="${b.id}" ${B.border === b.id ? "selected" : ""}>${esc(b.group)} — ${esc(b.name)} (+${money(b.price)})</option>`).join("")}</select></label>`;
    if (!combo && B.cat.allows_addons) {
      const whole = !SMALL_PIZZA.test(B.size);
      const chosen = Object.entries(B.addons).map(([id, q]) => { const a = D.addons.find((x) => x.id === Number(id)); return `<button type="button" class="chip-btn on" data-addon-del="${id}" aria-label="Tirar ${esc(a.name)}">${q}x ${esc(a.name)} ✕</button>`; }).join("");
      html += `<div class="addons"><span class="where-label">Adicionais</span><select data-addon-pick><option value="">Escolha um adicional…</option>${D.addons.map((a) => `<option value="${a.id}">${esc(a.name)} (+${money(whole ? a.price_whole : a.price_half)})</option>`).join("")}</select>
        <button type="button" class="ghost small" data-addon-add>+ Adicionar</button>${chosen}<small class="hint">até 5 por pizza</small></div>`;
    }
    const c = comboOf(B.cat);
    if (combo && c.choice_options.length) html += `<label class="grow">${esc(c.choice_label || "Escolha")}<select data-choice><option value="">Escolha…</option>${c.choice_options.map((o) => `<option ${B.choice === o ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
    html += `<div class="row"><label class="grow2">Observação<input data-notes value="${esc(B.notes)}" maxlength="200" placeholder="Ex.: sem cebola"></label>
      <label class="money">Quantidade<input type="number" min="1" max="50" value="${B.qty}" data-qty></label></div>
      <div class="row"><b class="pos-unit">${money(unitPrice())} cada</b><button type="button" class="primary" data-add>Adicionar ao pedido</button></div>`;
    builder.innerHTML = html;
  }
  builder.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.flavor !== undefined) {
      const f = flavorPool().find((x) => x.id === Number(t.value));
      B.flavors[Number(t.dataset.flavor)] = f || null;
      if (!borderOptions().some((b) => b.id === B.border)) B.border = null;
      renderBuilder();  // calzone esconde a borda
      return;
    }
    else if (t.hasAttribute("data-border")) B.border = t.value ? Number(t.value) : null;
    else if (t.hasAttribute("data-choice")) B.choice = t.value;
    else if (t.hasAttribute("data-qty")) B.qty = Math.max(1, Math.min(50, Number(t.value) || 1));
    else if (t.hasAttribute("data-notes")) B.notes = t.value;
    builder.querySelector(".pos-unit").textContent = `${money(unitPrice())} cada`;
  });
  builder.addEventListener("click", (e) => {
    const t = e.target;
    if (t.dataset.sizePick) { B.size = t.dataset.sizePick; B.flavors = []; B.border = null; renderBuilder(); }
    else if (t.dataset.n) { B.n = Number(t.dataset.n); B.flavors = B.flavors.slice(0, B.n); renderBuilder(); }
    else if (t.hasAttribute("data-add")) addItem();
    else if (t.hasAttribute("data-addon-add")) {
      const id = builder.querySelector("[data-addon-pick]").value;
      const total = Object.values(B.addons).reduce((a, b) => a + b, 0);
      if (id && total < 5) { B.addons[id] = (B.addons[id] || 0) + 1; renderBuilder(); }
    }
    else if (t.dataset.addonDel) { delete B.addons[t.dataset.addonDel]; renderBuilder(); }
  });
  function addItem() {
    const flavors = B.flavors.slice(0, B.n).filter(Boolean);
    if (flavors.length < B.n) { showError(`Escolha ${B.n > 1 ? "os " + B.n + " sabores" : "o sabor"}.`); return; }
    const c = comboOf(B.cat);
    if (isCombo() && c.choice_options.length && !B.choice) { showError(`Escolha: ${c.choice_label}.`); return; }
    const border = D.borders.find((b) => b.id === B.border);
    const addons = Object.entries(B.addons).map(([id, q]) => ({ id: Number(id), qty: q }));
    const title = isCombo() ? `${B.cat.name}: ${flavors.map((f) => f.name).join(" + ")}`
      : flavors.length > 1 ? flavors.map((f) => `1/${flavors.length} ${f.name}`).join(" + ") : flavors[0].name;
    const detail = [B.size, border ? `Borda ${border.group.replace(/^Borda /, "")} - ${border.name}` : "",
      addons.length ? addons.map((a) => `${a.qty}x ${D.addons.find((x) => x.id === a.id).name}`).join(", ") : "",
      B.choice, B.notes ? `Obs: ${B.notes}` : ""].filter(Boolean).join(" · ");
    cart.push({ sel: { category_id: B.cat.id, variant: B.size, flavors: flavors.map((f) => f.id), border_id: B.border, addons, combo_choice: B.choice || null, notes: B.notes },
      title, detail, price: unitPrice(), qty: B.qty });
    showError("");
    B = Object.assign(B, { flavors: [], border: null, addons: {}, choice: "", qty: 1, notes: "" });
    renderBuilder();
    renderCart();
  }

  /* ---------- itens do pedido e total ---------- */
  function renderCart() {
    const box = $("#pos-cart");
    box.innerHTML = cart.length ? `<h3>No pedido</h3>` + cart.map((i, idx) =>
      `<div class="cart-line"><span><b>${i.qty}x ${esc(i.title)}</b><small>${esc(i.detail)}</small></span><span>${money(i.price * i.qty)}</span>
        <span class="q"><button type="button" class="ghost small" data-q="${idx}" data-d="-1" aria-label="Menos um">−</button><button type="button" class="ghost small" data-q="${idx}" data-d="1" aria-label="Mais um">+</button></span></div>`).join("")
      : `<p class="empty">Nenhum item ainda. Toque numa categoria acima.</p>`;
    renderTotal();
  }
  $("#pos-cart").addEventListener("click", (e) => {
    const b = e.target.closest("[data-q]");
    if (!b) return;
    const i = Number(b.dataset.q);
    cart[i].qty += Number(b.dataset.d);
    if (cart[i].qty <= 0) cart.splice(i, 1);
    renderCart();
  });
  function renderTotal() {
    const sub = cart.reduce((s, i) => s + i.price * i.qty, 0);
    const total = sub + (fee() || 0);
    $("#pos-total").innerHTML = `<div><span>Itens</span><b>${money(sub)}</b></div>${delivery() ? `<div><span>Entrega</span><b>${fee() === null ? "a combinar" : money(fee())}</b></div>` : ""}<div class="big"><span>Total</span><b>${money(total)}</b></div>${splitLine(total)}`;
    return total;
  }
  // dividir a conta: mesma conta do servidor (services/split.py)
  function splitLine(total) {
    const n = Number(form.split_people.value);
    if (!n) return "";
    const c = Math.round(total * 100), b = Math.floor(c / n), x = c - b * n;
    return `<div><span>Por pessoa (${n})</span><b>${x ? `${x} de ${money((b + 1) / 100)} e ${n - x} de ${money(b / 100)}` : `${money(b / 100)} cada`}</b></div>`;
  }
  // taxa da entrega: a do bairro da lista ou a digitada para "Outro bairro" (vazia = a combinar)
  function fee() {
    if (!delivery()) return 0;
    if (D.km) { const v = num($("#pos-km-fee").value); return v === null || isNaN(v) ? null : v; }
    const opt = $('[name="neighborhood"]').selectedOptions[0];
    if (other()) { const v = num($('[name="delivery_fee"]').value); return v === null || isNaN(v) ? null : v; }
    return opt && opt.value ? Number(opt.dataset.fee) + resFee() : 0;
  }
  function showError(msg) { const el = $("#pos-error"); el.textContent = msg; el.hidden = !msg; }

  /* ---------- lançar ---------- */
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const hood = f.get("neighborhood");
    const cash = f.get("payment_method") === "Dinheiro";
    const change = cash ? num(f.get("change_for")) : null;
    if (change !== null && !(change >= renderTotal())) {
      showError(`O troco tem que ser para um valor maior que o total (${money(renderTotal())}). Se não precisar de troco, deixe em branco.`);
      $('[name="change_for"]').focus();
      return;
    }
    if ((other() || (D.km && delivery())) && fee() === null && !confirm("Você não digitou a taxa de entrega. Lançar com a entrega “a combinar”?")) {
      $('[name="delivery_fee"]').focus();
      return;
    }
    const payload = {
      channel: channel(), table_label: f.get("table_label"), customer_name: f.get("customer_name"), customer_phone: f.get("customer_phone"),
      withdraw: !delivery(), street: f.get("street"), number: f.get("number"), complement: f.get("complement"),
      residence: f.get("residence"), building: f.get("residence") === "casa" ? "" : f.get("building"),
      neighborhood: hood === "__outro__" ? (f.get("other_neighborhood") || "").trim() : hood, reference: f.get("reference"),
      delivery_fee: other() || D.km ? fee() : null, cep: D.km ? f.get("cep") : "",
      payment_method: f.get("payment_method"), change_for: change, split_people: Number(f.get("split_people")) || null,
      items: cart.map((i) => Object.assign({}, i.sel, { quantity: i.qty })),
    };
    const btn = $("#pos-submit");
    btn.disabled = true; btn.textContent = "Lançando…";
    try {
      const r = await fetch(location.pathname, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": token }, body: JSON.stringify(payload) });
      // sessão expirada: o servidor devolve a tela de login (HTML), não JSON
      if (r.redirected || !(r.headers.get("content-type") || "").includes("json"))
        throw new Error("Sua sessão do painel expirou. Entre de novo em outra aba e toque em “Lançar pedido” outra vez: o pedido ainda não foi lançado.");
      const data = await r.json();
      if (!data.ok) throw new Error(data.error || "Não deu para lançar.");
      form.removeAttribute("data-track");
      location.href = data.redirect;
    } catch (err) {
      sent = false;
      showError(err.message || "Sem conexão. Tente de novo.");
      btn.disabled = false; btn.textContent = "Lançar pedido";
    }
  });

  // itens montados e ainda não lançados: avisa antes de sair da tela
  let sent = false;
  form.addEventListener("submit", () => { sent = true; }, true);
  window.addEventListener("beforeunload", (e) => { if (cart.length && !sent) { e.preventDefault(); e.returnValue = ""; } });

  applyChannel();
  renderCart();
})();
