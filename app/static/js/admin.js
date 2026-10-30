/* Painel: pedidos ao vivo com som, busca na lista e aviso de alterações não salvas. */
(function () {
  "use strict";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* navegador sem armazenamento */ } },
  };

  /* ---------- alterações não salvas ---------- */
  // formulários com data-track: avisa antes de sair da página se algo foi mudado e não foi salvo
  const dirty = new Set();
  document.querySelectorAll("form[data-track]").forEach((form) => {
    const mark = () => {
      if (dirty.has(form)) return;
      dirty.add(form);
      form.classList.add("dirty");
      form.querySelectorAll("button.primary").forEach((b) => b.classList.add("pulse"));
    };
    form.addEventListener("input", mark);
    form.addEventListener("change", mark);
    form.addEventListener("submit", () => dirty.clear());
  });
  window.addEventListener("beforeunload", (e) => {
    if (dirty.size) { e.preventDefault(); e.returnValue = ""; }
  });

  /* ---------- nova categoria: tamanhos sugeridos conforme o tipo ---------- */
  const newCat = document.getElementById("new-category");
  if (newCat) {
    const box = document.getElementById("sizes");
    const tpl = document.getElementById("size-row");
    const nameInput = newCat.querySelector('[name="name"]');
    const SUGGEST = {
      pizza: [["Broto", 1], ["Inteira", 2]],
      doce: [["Broto", 1], ["Inteira", 2]],
      lanche: [["Único", 1]],
      montar: [["300 ml", 2], ["500 ml", 3], ["700 ml", 4]],
      bebida: [["Lata 350ml", 1], ["2 litros", 1]],
    };
    // número de cada tamanho: sabores (pizza) ou complementos grátis (monte o seu); lanche e bebida não usam
    const fillMax = (select, value) => {
      const picks = kind() === "montar";
      const opts = picks ? Array.from({ length: 11 }, (_, n) => [n, `${n} grátis`])
        : [[1, "1 (inteira)"], [2, "2 (meio a meio)"], [3, "3 sabores"], [4, "4 sabores"]];
      select.innerHTML = opts.map(([v, l]) => `<option value="${v}">${l}</option>`).join("");
      select.value = String(value ?? (picks ? 2 : 2));
      const label = select.closest("label").querySelector("[data-max-label]");
      if (label) label.textContent = picks ? "Complementos" : "Sabores";
    };
    let touched = false;  // depois que o dono mexe nos tamanhos, não troca mais sozinho
    const kind = () => newCat.querySelector('[name="kind"]:checked').value;
    const renumber = () => box.querySelectorAll(".size-row").forEach((row, i) => {
      row.querySelector('[data-name="size_label"]').name = `size_label-${i}`;
      row.querySelector('[data-name="size_max"]').name = `size_max-${i}`;
      row.querySelector(".remove-size").hidden = box.children.length === 1;
    });
    const addRow = (label = "", max = 2) => {
      const row = tpl.content.firstElementChild.cloneNode(true);
      row.querySelector('[data-name="size_label"]').value = label;
      row.querySelector('[data-name="size_label"]').placeholder = {bebida: "Ex.: Lata 350ml", montar: "Ex.: 500 ml", lanche: "Ex.: Único"}[kind()] || "Ex.: Inteira";
      fillMax(row.querySelector('[data-name="size_max"]'), max);
      row.querySelector(".remove-size").addEventListener("click", () => { touched = true; row.remove(); renumber(); });
      row.addEventListener("input", () => { touched = true; });
      box.appendChild(row);
      renumber();
      showFor();
    };
    const showFor = () => newCat.querySelectorAll("[data-only]").forEach((el) => {
      el.hidden = !el.dataset.only.split(" ").includes(kind());
    });
    const applyKind = () => {
      nameInput.placeholder = nameInput.dataset["placeholder" + kind().charAt(0).toUpperCase() + kind().slice(1)];
      if (!touched) { box.innerHTML = ""; SUGGEST[kind()].forEach(([l, m]) => addRow(l, m)); }
      else box.querySelectorAll('[data-name="size_max"]').forEach((s) => fillMax(s));
      showFor();
    };
    newCat.querySelectorAll('[name="kind"]').forEach((r) => r.addEventListener("change", applyKind));
    document.getElementById("add-size").addEventListener("click", () => { touched = true; addRow("", ["bebida", "lanche"].includes(kind()) ? 1 : 2); });
    applyKind();
  }

  /* ---------- criar linha: campos de bebida ---------- */
  document.querySelectorAll("[data-kind-select]").forEach((select) => {
    const form = select.form;
    const size = form.querySelector("[data-drink-placeholder]");
    const normal = size.placeholder;
    const apply = () => {
      const drink = select.value === "bebida";
      form.querySelectorAll("[data-not-drink]").forEach((el) => { el.hidden = drink; });
      size.placeholder = drink ? size.dataset.drinkPlaceholder : normal;
    };
    select.addEventListener("change", apply);
    apply();
  });

  /* ---------- busca ---------- */
  // <input id="search" data-items=".seletor">: esconde itens cujo data-name não contém o texto, e seções vazias
  const search = document.getElementById("search");
  if (search) {
    const plain = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    const items = [...document.querySelectorAll(search.dataset.items)];
    const sections = [...document.querySelectorAll(search.dataset.sections)];
    const counter = document.getElementById("search-count");
    search.addEventListener("input", () => {
      const q = plain(search.value.trim());
      let shown = 0;
      items.forEach((el) => {
        const hit = !q || plain(el.dataset.name || "").includes(q);
        el.hidden = !hit;
        if (hit) shown++;
      });
      sections.forEach((sec) => {
        sec.hidden = !!q && !sec.querySelector(search.dataset.items + ":not([hidden])");
        sec.classList.toggle("searching", !!q);
      });
      if (counter) counter.textContent = q ? `${shown} encontrado(s)` : "";
    });
  }

  /* ---------- estoque: liga/desliga salva na hora ---------- */
  const urls = document.getElementById("stock-urls");
  if (urls) {
    const token = document.querySelector('meta[name="csrf-token"]').content;
    const post = (url, body) => fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(body),
    }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); });
    const paint = (input) => {
      const item = input.closest(".chip") || input.closest(".stock-item");
      item.classList.toggle("off", !input.checked);
      const state = item.querySelector(":scope > .state");
      if (state) state.textContent = input.checked ? "Disponível" : "Esgotado";
    };
    document.querySelectorAll("[data-toggle]").forEach((input) => {
      input.addEventListener("change", async () => {
        paint(input);
        try {
          await post(urls.dataset.toggleUrl, { type: input.dataset.toggle, id: Number(input.dataset.id), active: input.checked });
        } catch (e) {
          input.checked = !input.checked;
          paint(input);
          alert("Não deu para salvar. Confira a internet e tente de novo (se pedir, entre no painel outra vez).");
        }
      });
    });
    const bulk = document.querySelector(".bulk");
    const onlyOff = document.getElementById("only-off");
    const refreshBulk = () => {
      bulk.hidden = !(search && search.value.trim());
      if (onlyOff.checked) document.querySelectorAll(".stock-item").forEach((el) => { if (!el.classList.contains("off")) el.hidden = true; });
    };
    search && search.addEventListener("input", refreshBulk);
    onlyOff.addEventListener("change", () => { search.dispatchEvent(new Event("input")); refreshBulk(); });
    bulk.querySelectorAll("[data-bulk]").forEach((btn) => btn.addEventListener("click", async () => {
      const active = btn.dataset.bulk === "1";
      const rows = [...document.querySelectorAll('.stock-item[data-type="product"]:not([hidden])')];
      if (!rows.length || !confirm(`${active ? "Ativar" : "Desativar"} ${rows.length} sabor(es) encontrado(s)?`)) return;
      try {
        await post(urls.dataset.bulkUrl, { ids: rows.map((r) => Number(r.dataset.id)), active });
        rows.forEach((r) => { const i = r.querySelector('[data-toggle="product"]'); i.checked = active; paint(i); });
      } catch (e) {
        alert("Não deu para salvar. Confira a internet e tente de novo.");
      }
    }));
  }

  /* ---------- pedidos ao vivo ---------- */
  const live = document.getElementById("live");
  if (!live) return;
  const SOUND_KEY = "painel_som";
  const POLL_MS = 15000;
  let latest = Number(live.dataset.latest || 0);
  let audio = null;
  const soundBtn = live.querySelector(".sound");
  const status = live.querySelector(".live-status");
  const baseTitle = document.title;

  function beep() {
    if (!audio || audio.state !== "running") return false;
    [0, 0.25, 0.5].forEach((t, i) => {
      const osc = audio.createOscillator(), gain = audio.createGain();
      osc.frequency.value = i === 2 ? 1175 : 880;
      gain.gain.setValueAtTime(0.0001, audio.currentTime + t);
      gain.gain.exponentialRampToValueAtTime(0.4, audio.currentTime + t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + t + 0.2);
      osc.connect(gain).connect(audio.destination);
      osc.start(audio.currentTime + t);
      osc.stop(audio.currentTime + t + 0.22);
    });
    return true;
  }
  function showSoundState() {
    const on = audio && audio.state === "running";
    soundBtn.textContent = on ? "🔔 Som ligado" : "🔕 Ativar som de novos pedidos";
    soundBtn.classList.toggle("on", !!on);
  }
  function enableSound() {
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      audio.resume().then(showSoundState);
    } catch (e) { /* sem suporte a áudio */ }
  }
  soundBtn.addEventListener("click", () => {
    if (audio && audio.state === "running") {
      audio.suspend().then(showSoundState);
      store.set(SOUND_KEY, "0");
    } else {
      store.set(SOUND_KEY, "1");
      enableSound();
      setTimeout(beep, 150);
    }
  });
  // o navegador só libera som depois de um clique na página: se o dono já tinha ligado, liga no primeiro clique
  if (store.get(SOUND_KEY) === "1") {
    enableSound();
    document.addEventListener("click", () => { if (store.get(SOUND_KEY) === "1") enableSound(); }, { once: true });
  }
  showSoundState();

  async function refreshList() {
    const html = await (await fetch(location.href, { credentials: "same-origin" })).text();
    const fresh = new DOMParser().parseFromString(html, "text/html").getElementById("orders-list");
    const current = document.getElementById("orders-list");
    if (fresh && current) current.replaceWith(fresh);
  }

  let waiting = false; // há pedido novo esperando o toque em “toque para ver”
  async function poll() {
    try {
      const r = await fetch(`${live.dataset.poll}?desde=${latest}`, { credentials: "same-origin" });
      if (r.redirected) { status.textContent = "Sessão expirada: entre de novo para continuar recebendo pedidos."; return; }
      if (!r.ok) { status.textContent = "Sem conexão com o servidor. Tentando de novo…"; return; } // ex.: site sendo atualizado
      const data = await r.json();
      document.querySelectorAll(".tabs .badge").forEach((b) => { b.textContent = data.pending; b.hidden = !data.pending; });
      if (data.new.length) {
        latest = data.latest;
        const last = data.new[data.new.length - 1];
        status.textContent = `Novo pedido #${last.id} — ${last.name} · ${last.total}`;
        status.classList.add("alert");
        document.title = `(${data.new.length}) Novo pedido! · ${baseTitle}`;
        beep();
        // a lista só se troca sozinha com a tela no topo; rolada, um toque errado cairia em outro pedido
        if (window.scrollY < 80) await refreshList();
        else {
          waiting = true;
          status.innerHTML = "";
          const see = document.createElement("button");
          see.type = "button";
          see.className = "primary small";
          see.textContent = `${data.new.length > 1 ? data.new.length + " pedidos novos" : "Pedido novo #" + last.id} — toque para ver`;
          see.addEventListener("click", async () => { waiting = false; await refreshList(); window.scrollTo({ top: 0 }); status.textContent = "Lista atualizada."; });
          status.appendChild(see);
        }
      } else if (!waiting) {
        status.textContent = `Atualizado às ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
      }
    } catch (e) {
      status.textContent = "Sem conexão. Tentando de novo…";
    }
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = baseTitle; });
  setInterval(poll, POLL_MS);
})();

/* Aberta/fechada no topo do painel: acompanha a loja sem recarregar (outra aba, outro celular ou o horário virando). */
(function () {
  "use strict";
  const pill = document.querySelector(".pill[data-status]");
  if (!pill) return;
  const card = document.querySelector(".store-now[data-open]");
  async function check() {
    try {
      const r = await fetch(pill.dataset.status, { credentials: "same-origin", cache: "no-store" });
      const open = (await r.json()).open;
      pill.classList.toggle("on", open); pill.classList.toggle("off", !open);
      pill.textContent = open ? "Aberta" : "Fechada";
      // a tela Início mostra o botão certo (Abrir/Fechar): se mudou, recarrega ela
      if (card && card.dataset.open !== (open ? "1" : "0")) location.reload();
    } catch (e) { /* sem conexão: tenta de novo na próxima */ }
  }
  setInterval(check, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
})();

/* Loja → horário: avisa quando o fechamento fica para a madrugada do dia seguinte. */
document.querySelectorAll(".next-day").forEach((note) => {
  const row = note.parentElement;
  const [o, c] = ["open", "close"].map((k) => row.querySelector(`input[name^="${k}-"]`));
  // fechar antes de abrir, até as 06:00 (ex.: 18:00 → 01:00) = fecha na madrugada seguinte
  const show = () => { note.hidden = !(o.value && c.value && c.value < o.value && c.value <= "06:00"); };
  [o, c].forEach((i) => i.addEventListener("input", show));
  show();
});
