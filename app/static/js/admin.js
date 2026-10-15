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

  async function poll() {
    try {
      const r = await fetch(`${live.dataset.poll}?desde=${latest}`, { credentials: "same-origin" });
      if (r.redirected || !r.ok) { status.textContent = "Sessão expirada: entre de novo para continuar recebendo pedidos."; return; }
      const data = await r.json();
      document.querySelectorAll(".tabs .badge").forEach((b) => { b.textContent = data.pending; b.hidden = !data.pending; });
      if (data.new.length) {
        latest = data.latest;
        const last = data.new[data.new.length - 1];
        status.textContent = `Novo pedido #${last.id} — ${last.name} · ${last.total}`;
        status.classList.add("alert");
        document.title = `(${data.new.length}) Novo pedido! · ${baseTitle}`;
        beep();
        await refreshList();
      } else {
        status.textContent = `Atualizado às ${new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
      }
    } catch (e) {
      status.textContent = "Sem conexão. Tentando de novo…";
    }
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) document.title = baseTitle; });
  setInterval(poll, POLL_MS);
})();
