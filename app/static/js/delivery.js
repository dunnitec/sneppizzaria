const DATA=window.DELIVERY_DATA;
const money=v=>"R$ "+v.toFixed(2).replace(".",",");
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let cart=[];

/* ---------- banner ---------- */
let bi=0;const bimgs=[...document.querySelectorAll("#banner .sl")];
(function(){const d=document.getElementById("dots");bimgs.forEach((_,i)=>d.insertAdjacentHTML("beforeend",`<i onclick="goSlide(${i})"></i>`));goSlide(0);
 if(bimgs.length>1)setInterval(()=>slide(1),6000);})();
function goSlide(i){if(!bimgs.length)return;bi=(i+bimgs.length)%bimgs.length;bimgs.forEach((im,k)=>im.classList.toggle("on",k===bi));document.querySelectorAll("#dots i").forEach((x,k)=>x.classList.toggle("on",k===bi));}
function slide(n){goSlide(bi+n);}
bimgs.forEach(sl=>{const im=sl.querySelector("img");sl.style.backgroundImage=`url(${im.src})`;const f=()=>{if(im.naturalWidth/im.naturalHeight>1.4)sl.classList.add("wide");};im.complete?f():im.onload=f;});

/* ---------- popups / status ---------- */
function togglePop(id,ev){ev.stopPropagation();const p=document.getElementById(id);const on=p.classList.contains("on");document.querySelectorAll(".pop").forEach(x=>x.classList.remove("on"));if(!on)p.classList.add("on");}
document.addEventListener("click",()=>document.querySelectorAll(".pop").forEach(x=>x.classList.remove("on")));
// aberto/fechado vem do servidor (horário de Brasília); a prévia estática não tem servidor e usa o relógio local
let CLOSED=DATA.open===false;
const CLOSED_MSG="Estamos fechados no momento. Confira nossos horários de atendimento.";
function showStatus(open){
  CLOSED=!open;
  document.getElementById("st-dot").classList.toggle("open",open);
  document.getElementById("st-txt").textContent=open?"Aberto":"Fechado";
  const f=document.getElementById("ft-st"); f.textContent=open?"◉ Aberto!":"◉ Fechado!"; f.classList.toggle("open",open);
}
(function status(){
  let open=DATA.open;
  if(open===undefined){
    const now=new Date(), d=now.getDay(), m=now.getHours()*60+now.getMinutes();
    const h=DATA.hours[d], y=DATA.hours[(d+6)%7]; open=false;
    if(h){const [a,b]=h; open = m>=a && m<b;}
    if(y&&y[1]>1440&&m<y[1]-1440)open=true; // expediente de ontem que vai até a madrugada
    showStatus(open);return;
  }
  showStatus(open);
  // o dono pode abrir/fechar pelo painel (ou o horário virar) com o site já aberto: confere de tempos em tempos
  const url=DATA.order_url.replace(/api\/.*$/,"api/status");
  const check=()=>fetch(url,{cache:"no-store"}).then(r=>r.json()).then(r=>{
    if(r.open===!CLOSED)return;
    showStatus(r.open);
    if(typeof renderCart==="function")renderCart();
    toast(r.open?"A loja abriu! Já dá para fazer o pedido.":CLOSED_MSG);
  }).catch(()=>{});
  setInterval(check,30000);
  document.addEventListener("visibilitychange",()=>{if(!document.hidden)check();});
})();

/* ---------- ícones dos títulos (painel → categoria → Como aparece no site) ---------- */
const ICONS={
  fatia:'<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"><path d="M6 10c13-6 27-6 36 0L24 44z"/><path d="M9 16c10-4 20-4 30 0"/><circle cx="20" cy="24" r="2.6" fill="currentColor"/><circle cx="28" cy="21" r="2.2" fill="currentColor"/><circle cx="24" cy="32" r="2.2" fill="currentColor"/></svg>',
  coroa:'<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"><path d="M6 16l9 9 9-14 9 14 9-9-4 22H10z"/><path d="M10 42h28"/><circle cx="6" cy="14" r="2.5" fill="currentColor"/><circle cx="24" cy="9" r="2.5" fill="currentColor"/><circle cx="42" cy="14" r="2.5" fill="currentColor"/></svg>',
  trem:'<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"><rect x="11" y="5" width="26" height="30" rx="7"/><path d="M11 21h26M18 11h12"/><circle cx="18" cy="28" r="2" fill="currentColor"/><circle cx="30" cy="28" r="2" fill="currentColor"/><path d="M16 35l-6 8M32 35l6 8M14 40h20"/></svg>',
  copo:'<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"><path d="M12 14h24l-3 30H15z"/><path d="M24 14l4-10h6"/><path d="M14 24h20"/></svg>',
  estrela:'<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"><path d="M24 5l5.9 12 13.1 1.9-9.5 9.3 2.3 13.1L24 35.1l-11.8 6.2 2.3-13.1L5 18.9l13.1-1.9z"/></svg>',
  fogo:'<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"><path d="M24 44c-9 0-15-6-15-14 0-9 8-13 9-22 6 4 9 9 9 14 2-2 3-5 3-8 6 4 9 10 9 16 0 8-6 14-15 14z"/><path d="M24 44c-4 0-6-3-6-6 0-4 4-6 5-10 3 3 7 6 7 10 0 3-2 6-6 6z"/></svg>',
  coracao:'<svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"><path d="M24 42S6 31 6 18a9 9 0 0 1 18-4 9 9 0 0 1 18 4c0 13-18 24-18 24z"/></svg>'
};
/* ---------- promoções (painel → Promoções); o preço com desconto já vem calculado do servidor ---------- */
const PROMOS=DATA.promotions||[];
function catPromo(c){for(const p of c.products||[])for(const v of p.variants)if(v.promo)return v.promo;return "";}
function was(v){return v&&v.regular?`<s class="was">${money(v.regular)}</s>`:"";}
function catHead(cat){
  const c=cat.raw||{}, w=cat.name.trim().split(/\s+/), top=w.length>1?w[0]:"", big=w.length>1?w.slice(1).join(" "):w[0];
  return `<div class="cat-head acc-${esc(c.accent||"vermelho")}"${c.banner?` style="--photo:url('${esc(c.banner)}')"`:""}>
    <span class="cat-ico" aria-hidden="true">${ICONS[c.icon]||ICONS.fatia}</span>
    <div><h2 class="cat-title">${top?`<span class="top">${esc(top)}</span>`:""}<span class="big">${esc(big)}</span></h2>${c.subtitle?`<p class="cat-sub">${esc(c.subtitle)}</p>`:""}</div>${catPromo(c)?`<span class="cat-promo">Promoção</span>`:""}</div>`;
}

/* ---------- menu ---------- */
const CATS=[];  // {name, slug, kind, cards:[...]}
(function build(){
  const notes=[...(DATA.notices||[])];
  DATA.categories.filter(c=>c.kind==="metro"&&c.products.length).forEach(c=>notes.push(comboNote(c)));
  if(notes.length)CATS.push({name:"Recados",slug:"recados",kind:"notice",cards:[{notice:true,lines:notes}]});
  DATA.categories.forEach(c=>{
    const cat={name:c.name,slug:c.slug,kind:c.kind,raw:c,cards:[]};
    if(c.kind==="metro"){
      const p=c.products[0], v=p.variants[0];
      const extras=comboOf(c).extras;
      cat.cards.push({title:p.name,desc:(p.description||"")+(extras.length?` Acompanha: ${extras.join(", ")}.`:""),fixed:v.price,was:v.regular||0,promo:v.promo||"",label:v.label,max:v.max_flavors,cat:c,sizes:Array.from({length:v.max_flavors},(_,i)=>i+1)});
    } else if(c.kind==="bebida"){
      // bebida: um card por item, um botão por tamanho; vai direto para a cesta
      c.products.forEach(p=>cat.cards.push({drink:true,p,cat:c,title:p.name}));
    } else {
      // agrupa por tamanho (variant label)
      const labels=[...new Set(c.products.flatMap(p=>p.variants.map(v=>v.label)))];
      labels.forEach(lb=>{
        const vs=c.products.map(p=>p.variants.find(v=>v.label===lb)).filter(Boolean), prices=vs.map(v=>v.price);
        const promo=(vs.find(v=>v.promo)||{}).promo||"", regMin=Math.min(...vs.map(v=>v.regular||v.price));
        const maxF=Math.max(...c.products.map(p=>(p.variants.find(v=>v.label===lb)||{}).max_flavors||1));
        cat.cards.push({title:lb,from:Math.min(...prices),was:regMin>Math.min(...prices)?regMin:0,promo,label:lb,max:maxF,cat:c,sizes:Array.from({length:maxF},(_,i)=>i+1)});
      });
    }
    CATS.push(cat);
  });
  const sel=document.getElementById("catsel"), box=document.getElementById("cats");
  CATS.forEach((cat,ci)=>{
    sel.insertAdjacentHTML("beforeend",`<option value="${cat.slug}">${esc(cat.name)}</option>`);
    const cards=cat.cards.map((k,ki)=>{
      if(k.notice) return "";
      if(k.drink) return `<div class="card drink" data-name="${esc(k.title)}"><div class="top">${k.p.image?`<img class="th" src="${esc(k.p.image)}" alt="" loading="lazy">`:""}<div><h3>${esc(k.title)}</h3>${k.p.description?`<p class="desc">${esc(k.p.description)}</p>`:""}</div></div><div class="btns">${k.p.variants.map((v,vi)=>`<button class="${v.promo?"has-promo":""}" onclick="addDrink(${ci},${ki},${vi})">${esc(v.label)}<small>${was(v)}${money(v.price)}</small>${v.promo?`<i class="promo-tag">${esc(v.promo)}</i>`:""}</button>`).join("")}</div></div>`;
      const btns=k.sizes.map((n,i)=>`<button class="${i===k.sizes.length-1?"main-btn":""}" onclick="startFlow(${ci},${ki},${n})">${n} sabor${n>1?"es":""}</button>`).join("");
      const tag=k.promo?`<span class="promo-tag">🏷 ${esc(k.promo)}</span>`:"";
      if(k.fixed) return `<div class="card full ${k.promo?"has-promo":""}" data-name="${esc(k.title)}">${tag}<div class="top"><div><h3>${esc(k.title)}</h3><p class="desc">${esc(k.desc)}</p><p class="price">${k.was?`<s class="was">${money(k.was)}</s> `:""}${money(k.fixed)}</p></div></div><div class="btns">${btns}</div></div>`;
      return `<div class="card ${k.promo?"has-promo":""}" data-name="${esc(k.title)}">${tag}<div class="top"><h3>${esc(k.title)}</h3><span class="from">${k.was?`<span>A partir de <s class="was">${money(k.was)}</s></span>`:"A partir de "}<b>${money(k.from)}</b></span></div><div class="btns">${btns}</div></div>`;
    }).join("");
    if(cat.kind==="notice"){box.insertAdjacentHTML("beforeend",`<section class="cat" id="cat-${cat.slug}" data-slug="${cat.slug}"><div class="notice"><span class="notice-ico" aria-hidden="true">!</span><div><h2>Recados</h2>${cat.cards[0].lines.map(l=>`<p>${esc(l)}</p>`).join("")}</div></div></section>`);return;}
    box.insertAdjacentHTML("beforeend",`<section class="cat" id="cat-${cat.slug}" data-slug="${cat.slug}">${catHead(cat)}<div class="grid">${cards}</div></section>`);
  });
})();
// vai até a categoria sem esconder as outras (usado pelo aviso de promoções)
function goCat(slug){const sel=document.getElementById("catsel");if(sel)sel.value="";jumpCat("");const el=document.getElementById("cat-"+slug);if(el)el.scrollIntoView({behavior:"smooth"});}
function jumpCat(slug){document.querySelectorAll(".cat").forEach(s=>s.style.display=(!slug||slug==="all"||s.dataset.slug===slug)?"":"none");if(slug&&slug!=="all")document.getElementById("cat-"+slug).scrollIntoView({behavior:"smooth"});}
function filterMenu(){
  const qi=document.getElementById("q"); if(!qi)return;
  const q=qi.value.trim().toLowerCase();
  document.querySelectorAll(".cat").forEach(s=>{
    const cat=CATS.find(c=>c.slug===s.dataset.slug);
    if(!q){s.style.display="";return;}
    const hit=cat.kind!=="notice"&&(cat.name.toLowerCase().includes(q)||(cat.cards[0].cat||{products:[]}).products.some(p=>p.name.toLowerCase().includes(q)));
    s.style.display=hit?"":"none";
  });
}

/* ---------- fluxo (modal em etapas) ---------- */
let F=null; // {card, n, step, flavors:[], border:null, addons:{}, qty, notes}
function startFlow(ci,ki,n){
  const k=CATS[ci].cards[ki];
  F={card:k,n,step:0,flavors:[],border:null,addons:{},choice:null,qty:1,notes:""};
  renderStep();
  document.getElementById("ovl").classList.add("on");
}
function addDrink(ci,ki,vi){
  if(CLOSED){toast(CLOSED_MSG);return;}
  const k=CATS[ci].cards[ki], v=k.p.variants[vi];
  const same=cart.find(i=>i.sel.category_id===k.cat.id&&i.sel.flavors[0]===k.p.id&&i.variant===v.label);
  if(same)same.qty++;
  else cart.push({sel:{category_id:k.cat.id,variant:v.label,flavors:[k.p.id],border_id:null,addons:[],combo_choice:null},
    title:k.p.name,variant:v.label,border:"",addons:"",extras:"",notes:"",price:v.price,qty:1});
  renderCart();toast(`${k.p.name} (${v.label}) adicionado à cesta.`);
}
// toque fora da janela: fecha, menos em formulário (cadastro, entrar, finalizar pedido), que só fecha no X
function backdropClose(){
  if(document.querySelector("#md #accf, #md #ckf")){
    const x=document.querySelector("#md .x");if(x){x.classList.remove("nudge");void x.offsetWidth;x.classList.add("nudge");}
    toast("Para fechar, toque no X.");return;
  }
  closeModal();
}
function closeModal(){document.getElementById("ovl").classList.remove("on");F=null;}
function flavorPool(){
  const k=F.card;
  if(k.cat.kind==="metro"){const src=comboOf(k.cat).sources;return DATA.categories.filter(c=>c.kind!=="metro"&&src.includes(c.slug)).flatMap(c=>c.products.map(p=>({...p,price:k.fixed,fixed:true})));}
  return k.cat.products.map(p=>{const v=p.variants.find(v=>v.label===k.label);return v?{...p,price:v.price,regular:v.regular,promo:v.promo}:null;}).filter(Boolean);
}
function isPremium(){return !!F.card.cat.allows_addons;}
function borderLabel(b){return b.group.replace(/^Borda /,"")+" - "+b.name;}
// bordas que valem para a pizza escolhida (o dono define em Bordas e adicionais → Onde aparece)
function borderOptions(){const k=F.card;return DATA.borders.map((b,i)=>({b,i})).filter(({b})=>!(b.no_sizes||[]).includes(k.label)&&!(b.no_categories||[]).includes(k.cat.slug));}
// combo (kind "metro"): preço fixo, sabores das linhas escolhidas no painel, brindes e uma pergunta opcional ao cliente
function comboOf(c){const x=c.combo||{};return {sources:x.sources||[],extras:x.extras||[],choice_label:x.choice_label||"",choice_options:x.choice_options||[]};}
function lineName(slug){const c=DATA.categories.find(c=>c.slug===slug);return c?c.name.replace(/^Pizzas? /i,""):slug;}
function comboNote(c){
  const src=comboOf(c).sources.map(lineName), max=c.products[0].variants[0].max_flavors;
  const lines=src.length>1?`das linhas ${src.slice(0,-1).join(", ")} e ${src[src.length-1]}`:`da linha ${src[0]||""}`;
  return `${c.name}: preço fixo, até ${max} sabor${max>1?"es":""} ${lines}.`;
}
function isCombo(){return F.card.cat.kind==="metro";}
function comboExtras(){if(!isCombo())return "";const c=comboOf(F.card.cat),x=[...c.extras];if(c.choice_options.length&&F.choice)x.push(`${c.choice_label||"Escolha"}: ${F.choice}`);return x.join(", ");}
function steps(){const s=[];for(let i=0;i<F.n;i++)s.push({type:"flavor",i});
  if(isCombo()){if(comboOf(F.card.cat).choice_options.length)s.push({type:"choice"});}
  else{if(borderOptions().length)s.push({type:"border"});if(isPremium())s.push({type:"addons"});}
  s.push({type:"confirm"});return s;}
function ordinal(i){return `${i+1}º`;}
function unitPrice(){
  const k=F.card; let p;
  if(k.cat.kind==="metro") p=k.fixed; else p=Math.max(...F.flavors.map(f=>f.price));
  if(F.border!=null) p+=DATA.borders[F.border].price;
  const whole=/inteira|grande/i.test(k.label);
  Object.entries(F.addons).forEach(([i,q])=>{const a=DATA.addons[i];p+=q*(whole?a.price_whole:a.price_half);});
  return p;
}
function renderStep(){
  const prevBody=document.querySelector("#md .body"), sameStep=F._shown===F.step, keepTop=sameStep&&prevBody?prevBody.scrollTop:0;
  if(!sameStep)F.q="";
  const st=steps()[F.step], md=document.getElementById("md"); let t="",sub="",body="",nextOk=true,nextLbl="Avançar ›";
  if(st.type==="flavor"){
    t=`Escolha o ${ordinal(st.i)} sabor.`;
    const cur=F.flavors[st.i];
    body=`<input class="srch" placeholder="Busque por um sabor" value="${esc(F.q||"")}" oninput="F.q=this.value;fl(this.value)"><div id="fl">`+flavorPool().map((p,pi)=>`<div class="opt ${cur&&cur.name===p.name?"sel":""}" data-n="${esc(p.name.toLowerCase())}" onclick="pickFlavor(${pi})">${p.image?`<img class="th" src="${esc(p.image)}" alt="" loading="lazy">`:""}<div class="grow"><div class="n">${esc(p.name)}${!p.fixed&&rewardTag(F.card,p.id)?` <i class="gift-tag">🎁 vale no seu prêmio</i>`:""}</div><div class="d">${esc(p.description||"")}</div>${p.fixed?"":`<div class="p">${was(p)}${money(p.price)}${p.promo?` <i class="promo-tag">${esc(p.promo)}</i>`:""}</div>`}</div></div>`).join("")+`</div>`;
    nextOk=!!cur;
  } else if(st.type==="choice"){
    const c=comboOf(F.card.cat); t=c.choice_label||"Escolha uma opção"; sub="Vem junto com o combo.";
    body=c.choice_options.map((o,i)=>`<div class="opt" onclick="F.choice=comboOf(F.card.cat).choice_options[${i}];renderStep()"><input type="radio" ${F.choice===o?"checked":""}><div class="grow" style="font-weight:400">${esc(o)}</div></div>`).join("");
    nextOk=!!F.choice;
  } else if(st.type==="border"){
    t="Bordas Recheadas"; sub="Escolha 1 opção para a pizza.";
    const groups=[...new Set(DATA.borders.map(b=>b.group))];
    body=`<div class="opt" onclick="F.border=null;renderStep()"><input type="radio" ${F.border==null?"checked":""}><div class="grow n" style="font-weight:400">Sem borda</div></div>`+
      borderOptions().map(({b,i})=>`<div class="opt" onclick="F.border=${i};renderStep()"><input type="radio" ${F.border===i?"checked":""}><div class="grow" style="font-weight:400">${esc(b.group)} — ${esc(b.name)}</div><span class="pr">${money(b.price)}</span></div>`).join("");
  } else if(st.type==="addons"){
    t="Adicionais"; sub=`Escolha entre 0 e 5 opções para a pizza.`;
    const whole=/inteira/i.test(F.card.label);
    body=DATA.addons.map((a,i)=>`<div class="opt" style="cursor:default"><div class="cnt"><button class="m" onclick="addon(${i},-1)">−</button><span>${F.addons[i]||0}</span><button class="p" onclick="addon(${i},1)">+</button></div><div class="grow" style="font-weight:400">${esc(a.name)}</div><span class="pr">${money(whole?a.price_whole:a.price_half)}</span></div>`).join("");
  } else {
    t="Confirmação"; sub="Escolha a quantidade do item"; nextLbl="Adicionar";
    const k=F.card, up=unitPrice();
    const ttl=k.cat.kind==="metro"?`${k.title}`:`PIZZA ${k.cat.name.replace(/^Pizzas? /i,"")} ${k.label} (${F.n} sabor${F.n>1?"es":""})`;
    body=`<div class="conf"><div class="row"><div><div class="ttl">${esc(ttl)}</div>${F.flavors.map(f=>`<div class="sub">1 x ${F.n>1?"1/"+F.n+" ":""}${esc(f.name)}</div>`).join("")}${F.border!=null?`<div class="sub">Borda: ${esc(borderLabel(DATA.borders[F.border]))}</div>`:""}${Object.entries(F.addons).filter(([,q])=>q>0).map(([i,q])=>`<div class="sub">${q} x ${esc(DATA.addons[i].name)}</div>`).join("")}${comboExtras()?`<div class="sub">Acompanha: ${esc(comboExtras())}</div>`:""}</div>
      <div><div class="cnt" style="display:flex;gap:8px;align-items:center;justify-content:flex-end"><button class="m" style="width:22px;height:22px;border-radius:50%;border:0;background:#e31c1c;color:#fff;font-weight:700" onclick="F.qty=Math.max(1,F.qty-1);renderStep()">−</button><span>${F.qty}</span><button style="width:22px;height:22px;border-radius:50%;border:0;background:#2fb344;color:#fff;font-weight:700" onclick="F.qty++;renderStep()">+</button></div>
      <div class="big">${money(up*F.qty)}<small>${money(up)}</small></div></div></div>
      <textarea placeholder="Observações" oninput="F.notes=this.value">${esc(F.notes)}</textarea>
      ${k.cat.kind==="metro"?`<p class="note">*${esc(k.cat.name)}: preço fixo, independente dos sabores.</p>`:`<p class="note">*O valor da pizza será definido pelo sabor de maior valor.</p>`}</div>`;
  }
  md.innerHTML=`<button class="x" onclick="closeModal()">×</button><div class="t"><h2>${t}</h2>${sub?`<p>${sub}</p>`:""}</div><div class="body">${body}</div>
    <div class="ft">${F.step>0?`<button class="bk" onclick="F.step--;renderStep()">‹ Voltar</button>`:""}<button class="nx" ${nextOk?"":"disabled"} onclick="next()">${nextLbl}</button></div>`;
  F._shown=F.step;
  if(F.q)fl(F.q);
  const b=md.querySelector(".body"); if(b)b.scrollTop=keepTop;
}
function fl(q){q=q.toLowerCase();document.querySelectorAll("#fl .opt").forEach(o=>o.style.display=o.dataset.n.includes(q)?"":"none");}
function pickFlavor(pi){F.flavors[steps()[F.step].i]=flavorPool()[pi];renderStep();}
function addon(i,d){const tot=Object.values(F.addons).reduce((s,q)=>s+q,0);const cur=F.addons[i]||0;if(d>0&&tot>=5)return;F.addons[i]=Math.max(0,cur+d);if(!F.addons[i])delete F.addons[i];renderStep();}
function next(){
  const s=steps();
  if(s[F.step].type==="confirm"){
    const k=F.card;
    const title=k.cat.kind==="metro"?`${k.cat.name}: ${F.flavors.map(f=>f.name).join(" + ")}`:(F.n>1?F.flavors.map(f=>`1/${F.n} ${f.name}`).join(" + "):F.flavors[0].name);
    // sel = o que foi escolhido (ids); é isso que o servidor usa para calcular o preço. O restante é só exibição.
    const sel={category_id:k.cat.id,variant:k.label,flavors:F.flavors.map(f=>f.id),border_id:F.border!=null?DATA.borders[F.border].id:null,addons:Object.entries(F.addons).map(([i,q])=>({id:DATA.addons[i].id,qty:q})),combo_choice:F.choice||null};
    const base=isCombo()?k.fixed:Math.max(...F.flavors.map(f=>f.price));
    cart.push({sel,base,title,variant:k.label,border:F.border!=null?borderLabel(DATA.borders[F.border]):"",addons:Object.entries(F.addons).map(([i,q])=>`${q}x ${DATA.addons[i].name}`).join(", "),extras:comboExtras(),notes:F.notes.trim(),price:unitPrice(),qty:F.qty});
    closeModal();renderCart();toast("Item adicionado à cesta.");return;
  }
  F.step++;renderStep();
}

/* ---------- cesta ---------- */
function subtotal(){return cart.reduce((s,i)=>s+i.price*i.qty,0);}
function renderCart(){
  const c=document.getElementById("cart");
  document.getElementById("mbar-total").textContent=money(subtotal());
  const cnt=document.getElementById("mbar-count"); if(cnt)cnt.textContent=cart.reduce((s,i)=>s+i.qty,0);
  if(!cart.length){c.innerHTML=`<div class="empty"><span class="ic" aria-hidden="true">🛒</span>Sua cesta ainda está vazia. Escolha uma pizza ao lado.</div>`;return;}
  const wd=document.getElementById("withdraw").checked;
  c.innerHTML=`<div class="hd"><span>🛒 Sua cesta</span><span>${cart.reduce((s,i)=>s+i.qty,0)} item(ns)</span></div>`+
    cart.map((i,idx)=>`<div class="ci"><div><b>${esc(i.title)}</b><small>${esc(i.variant)}${i.border?" · Borda "+esc(i.border):""}${i.addons?" · "+esc(i.addons):""}${i.extras?" · Acompanha: "+esc(i.extras):""}${i.notes?" · Obs: "+esc(i.notes):""}</small><span class="lt">${money(i.price*i.qty)}</span></div>
      <div class="q"><button class="m" onclick="qty(${idx},-1)">−</button>${i.qty}<button class="p" onclick="qty(${idx},1)">+</button></div></div>`).join("")+
    `<div class="ct"><span>Subtotal</span><span>${money(subtotal())}</span></div><div class="ct"><span>Entrega</span><span>${wd?"retirada":"por bairro"}</span></div>
     ${DATA.min_order&&subtotal()<DATA.min_order?`<p class="closed-note">Pedido mínimo: ${money(DATA.min_order)} (sem a entrega).</p>`:""}
     ${CLOSED?`<p class="closed-note">${CLOSED_MSG}</p>`:`<button class="go" onclick="openCheckout()">Finalizar pedido</button>`}`;
}
function qty(i,d){cart[i].qty+=d;if(cart[i].qty<=0)cart.splice(i,1);renderCart();}
function openCart(){
  if(!cart.length){toast("Sua cesta ainda está vazia.");return;}
  const md=document.getElementById("md");
  md.innerHTML=`<button class="x" onclick="closeModal()">×</button><div class="t"><h2>Sua cesta</h2></div><div class="body" style="padding:0"><div class="withdraw" style="margin:10px 16px;border:1px solid #ddd"><div>Retirar na loja<small>${esc(DATA.tenant.address)}</small></div><input type="checkbox" ${document.getElementById("withdraw").checked?"checked":""} onchange="document.getElementById('withdraw').checked=this.checked;renderCart()"></div>
    ${cart.map((i,idx)=>`<div class="ci"><div><b>${esc(i.title)}</b><small>${esc(i.variant)}${i.border?" · Borda "+esc(i.border):""}${i.addons?" · "+esc(i.addons):""}${i.extras?" · Acompanha: "+esc(i.extras):""}</small><span class="lt">${money(i.price*i.qty)}</span></div><div class="q"><button class="m" onclick="qty(${idx},-1);openCart()">−</button>${i.qty}<button class="p" onclick="qty(${idx},1);openCart()">+</button></div></div>`).join("")}
    <div class="ct tot"><span>Subtotal</span><span>${money(subtotal())}</span></div></div>
    <div class="ft"><button class="bk" onclick="closeModal()">‹ Voltar</button><button class="nx" onclick="openCheckout()">Finalizar pedido</button></div>`;
  document.getElementById("ovl").classList.add("on");
}
function toast(m){const t=document.getElementById("toast");t.textContent=m;t.classList.add("on");setTimeout(()=>t.classList.remove("on"),2200);}

/* ---------- checkout → WhatsApp ---------- */
function openCheckout(){
  if(!cart.length)return;
  if(CLOSED){toast(CLOSED_MSG);return;}
  if(DATA.min_order&&subtotal()<DATA.min_order){toast(`O pedido mínimo é de ${money(DATA.min_order)} (sem a entrega).`);return;}
  const wd=document.getElementById("withdraw").checked;
  const md=document.getElementById("md");
  md.innerHTML=`<button class="x" onclick="closeModal()">×</button><div class="t"><h2>Finalizar pedido</h2><p>${DATA.pix?"Pague pelo Pix aqui no site ou na entrega.":"Pagamento na entrega."} O pedido é enviado pelo WhatsApp.</p></div>
  <form class="body ck" id="ckf" onsubmit="return finish(event)">
    ${ckAccount()}
    <label>Nome<input name="nome" required></label>
    <label>Telefone / WhatsApp<input name="tel" type="tel" required ${ACC?"readonly":""}></label>
    <label style="display:flex;align-items:center;gap:8px;margin-top:12px"><input type="checkbox" id="ck-wd" style="width:18px;height:18px;margin:0" ${wd?"checked":""} onchange="document.getElementById('addr').style.display=this.checked?'none':'';totals()"> Retirar na loja</label>
    <div id="addr" style="${wd?"display:none":""}">
      <label>Rua<input name="rua"></label>
      <div class="r2"><label>Número<input name="num"></label><label>Complemento<input name="comp"></label></div>
      <label>Bairro<select name="bairro" id="bairro" onchange="totals()"><option value="">Selecione…</option>${DATA.neighborhoods.map(n=>`<option value="${esc(n.name)}">${esc(n.name)} — ${money(n.fee)}</option>`).join("")}<option value="__outro__">Outro bairro (taxa a confirmar)</option></select></label>
      <label>Ponto de referência<input name="ref"></label>
    </div>
    <label>Forma de pagamento<select name="pag" id="pag" required onchange="document.getElementById('troco').style.display=this.value==='Dinheiro'?'':'none';const pn=document.getElementById('pix-note');if(pn)pn.hidden=this.value!=='Pix'"><option value="">Selecione…</option>${DATA.tenant.accepted_payments.split(",").filter(p=>p.trim()).map(p=>`<option>${esc(p.trim())}</option>`).join("")}</select></label>${DATA.pix?`<p class="pix-note" id="pix-note" hidden>Pix: ao finalizar, aparece o QR Code e o “Pix copia e cola” com o valor do pedido para você pagar no app do banco.</p>`:""}
    <label id="troco" style="display:none">Troco para quanto? (opcional; maior que o total)<input name="troco" type="number" step="0.01" min="0" inputmode="decimal"></label>
    <div class="sum" id="sum"></div>
    <p class="privacy">Usamos seu nome, telefone e endereço só para entregar e falar sobre o seu pedido.</p>
  </form>
  <div class="ft"><button class="bk" type="button" onclick="openCart()">‹ Voltar</button><button class="nx" type="submit" form="ckf" style="background:#25d366">Enviar pelo WhatsApp</button></div>`;
  document.getElementById("ovl").classList.add("on");fillRemembered();fillAccount();totals();
}
// nome, telefone e endereço ficam salvos só neste aparelho, para o próximo pedido ser mais rápido
const REMEMBER_KEY="snep_cliente_"+DATA.tenant.slug;
/* ---------- Pix com QR Code (painel → Loja → Pix pelo site) ---------- */
function pixBox(r){
  if(r.pix_pending)return `<div class="pix-box"><p>Pix: como a taxa de entrega do seu bairro ainda vai ser confirmada, a pizzaria te manda o valor final pelo WhatsApp.</p></div>`;
  if(!r.pix)return "";
  return `<div class="pix-box"><h4>Pague com Pix</h4><p class="pix-amount">${money(r.pix.amount)}</p>
    <img class="pix-qr" src="${r.pix.qr}" alt="QR Code do Pix">
    <p class="pix-help">No app do banco: <b>Pix → Ler QR Code</b>. Ou copie o código e use <b>Pix copia e cola</b>:</p>
    <textarea class="pix-code" id="pix-code" readonly rows="3" onclick="this.select()">${esc(r.pix.code)}</textarea>
    <button type="button" class="btn-red pix-copy" onclick="copyPix(this)">Copiar código Pix</button></div>`;
}
function copyPix(btn){
  const ta=document.getElementById("pix-code"), ok=()=>{btn.textContent="Código copiado ✓";toast("Código Pix copiado. Cole no app do banco.");};
  if(navigator.clipboard&&window.isSecureContext)navigator.clipboard.writeText(ta.value).then(ok,()=>{ta.select();document.execCommand("copy");ok();});
  else{ta.select();document.execCommand("copy");ok();}
}
function remember(p){try{localStorage.setItem(REMEMBER_KEY,JSON.stringify({nome:p.customer_name,tel:p.customer_phone,rua:p.street,num:p.number,comp:p.complement,bairro:p.neighborhood,ref:p.reference}));}catch(e){}}
function fillRemembered(){
  let d=null;try{d=JSON.parse(localStorage.getItem(REMEMBER_KEY)||"null");}catch(e){}
  if(!d)return;
  const f=document.getElementById("ckf");
  ["nome","tel","rua","num","comp","ref"].forEach(k=>{const el=f.querySelector(`[name=${k}]`);if(el&&!el.value&&d[k])el.value=d[k];});
  const b=document.getElementById("bairro");if(d.bairro&&[...b.options].some(o=>o.value===d.bairro))b.value=d.bairro;
}
function fee(){
  if(document.getElementById("ck-wd").checked) return 0;
  const b=document.getElementById("bairro").value; if(!b||b==="__outro__") return null;
  const n=DATA.neighborhoods.find(x=>x.name===b); return n?n.fee:null;
}
function totals(){const f=fee(),s=subtotal(),d=accDiscount();document.getElementById("sum").innerHTML=`<div><span>Subtotal</span><span>${money(s)}</span></div>${d.value?`<div class="disc"><span>Desconto (${esc(d.note)})</span><span>-${money(d.value)}</span></div>`:""}<div><span>Entrega</span><span>${f===null?"a confirmar":money(f)}</span></div><div class="tt"><span>Total${f===null?" (sem entrega)":""}</span><span>${money(s-d.value+(f||0))}</span></div>`;}
function finish(ev){
  ev.preventDefault();const f=ev.target,wd=document.getElementById("ck-wd").checked;
  if(!wd&&(!f.rua.value||!f.num.value||!f.bairro.value)){toast("Preencha o endereço de entrega.");return false;}
  const cash=f.pag.value==="Dinheiro", troco=cash&&f.troco.value?Number(f.troco.value):null;
  const total=subtotal()-accDiscount().value+(fee()||0);
  if(troco!==null&&troco<total-0.004){toast(`O troco tem que ser para um valor maior que o total (${money(total)}).`);f.troco.focus();return false;}
  const payload={withdraw:wd,customer_name:f.nome.value,customer_phone:f.tel.value,street:wd?"":f.rua.value,number:wd?"":f.num.value,complement:wd?"":f.comp.value,
    neighborhood:wd?"":(f.bairro.value==="__outro__"?"":f.bairro.value),reference:wd?"":f.ref.value,payment_method:f.pag.value,change_for:troco,use_rewards:usedRewards(),push_endpoint:PUSH_ENDPOINT,
    items:cart.map(i=>({...i.sel,notes:i.notes,quantity:i.qty,title:i.title,border:i.border,addons_text:i.addons,extras_text:i.extras,unit_price:i.price}))};
  const btn=document.querySelector(".md .ft .nx");btn.disabled=true;btn.textContent="Enviando…";
  fetch(DATA.order_url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)})
    .then(r=>r.json()).then(r=>{
      if(!r.ok){toast(r.error||"Erro ao enviar pedido.");btn.disabled=false;btn.textContent="Enviar pelo WhatsApp";return;}
      document.getElementById("md").innerHTML=`<button class="x" onclick="closeModal()">×</button><div class="body succ"><h3>Pedido pronto! 🍕</h3>${r.order_id?`<p>Pedido <b>#${r.order_id}</b> · Total ${money(r.total)}${r.delivery_fee===null?" + entrega a confirmar":""}</p>`:""}${r.discount?`<p class="disc-ok">Desconto de ${money(r.discount)} (${esc(r.discount_note)}) ✓</p>`:""}${r.track_url?`<a class="btn-track" href="${r.track_url}">Acompanhar pedido ›</a>`:""}${pushAskHtml((r.track_url||"").split("/").pop())}${r.eta?`<p class="eta-box">${r.eta_label}: <b>${r.eta}</b></p>`:""}${pixBox(r)}<p>${r.pix?"Depois de pagar, abra o WhatsApp para enviar o pedido e o comprovante para a pizzaria.":"Clique abaixo para abrir o WhatsApp com o pedido preenchido e enviar para a pizzaria."}</p><a class="btn-red btn-wa" style="display:block;padding:14px;font-size:16px" href="${r.wa_link}" target="_blank" rel="noopener">Abrir WhatsApp</a></div><div class="ft"><button class="bk" style="flex:1" onclick="closeModal()">Fechar</button></div>`;
      remember(payload);cart=[];renderCart();accApi("").then(setAcc);
    }).catch(()=>{toast("Falha de conexão. Tente novamente.");btn.disabled=false;btn.textContent="Enviar pelo WhatsApp";});
  return false;
}
renderCart();

/* ---------- conta do cliente: cadastro pelo telefone, histórico, cartões fidelidade e 1º pedido ---------- */
let ACC=null, AFTER_LOGIN=null; // ACC = dados da conta logada (GET /api/conta)
async function accApi(path,body){
  try{
    const r=await fetch(DATA.account_url+path,{method:body?"POST":"GET",headers:body?{"Content-Type":"application/json"}:{},body:body?JSON.stringify(body):undefined,credentials:"same-origin"});
    return await r.json();
  }catch(e){return {ok:false,error:"Falha de conexão. Tente de novo."};}
}
function setAcc(j){
  ACC=j&&j.logged?j:null;renderAccCard();if(ACC&&typeof pushSync==="function")pushSync();
  const l=document.getElementById("acc-label");if(l)l.textContent=ACC?ACC.name.split(" ")[0]:"Entrar";
}
function perks(){const p=[];if(DATA.first_order)p.push(DATA.first_order.text);(DATA.loyalty||[]).forEach(x=>p.push(`Cartão ${x.name}: a cada ${x.goal} pizzas, ${x.reward}`));return p;}
function stampsHtml(l){let h='<div class="stamps">';for(let i=0;i<l.goal;i++)h+=`<span class="${i<l.filled?"on":""}">${i<l.filled?"🍕":i+1}</span>`;return h+`<span class="gift${l.rewards?" on":""}">🎁</span></div>`;}
function cardHtml(l,click){
  const head=l.full?`<b class="done">Cartão completo! 🎁 ${l.rewards>1?l.rewards+" pizzas grátis":"1 pizza grátis"} para usar</b>`
    :`${l.filled} de ${l.goal} selos${l.rewards?` · 🎁 ${l.rewards} grátis para usar`:` · a cada ${l.goal}, ${esc(l.reward_text)}`}`;
  return `<div class="acc-card${l.full?" full":""}"${click?` onclick="openAccount()" role="button" tabindex="0"`:""}><div class="acc-txt"><b>Cartão ${esc(l.name)}</b>
    <small>${head}<br>Você já comprou ${l.total_stamps} pizza${l.total_stamps===1?"":"s"} ${esc(l.name)}${l.full?" · o próximo cartão começa no seu próximo pedido":""}</small>
    ${l.pending?`<small class="pending">⏳ +${l.pending} selo${l.pending>1?"s":""} chegando: assim que a pizzaria confirmar seu pedido</small>`:""}</div>${stampsHtml(l)}</div>`;
}
// o cliente volta para o site (ex.: depois da pizzaria confirmar): atualiza o cartão
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible"&&ACC)accApi("").then(setAcc);});
// cartões lado a lado: o cliente arrasta para ver cada um (Promocional, Premium...)
function sliderHtml(cs,click){
  return `<div class="acc-slider"><div class="acc-track" onscroll="slideDots(this)">${cs.map(l=>cardHtml(l,click)).join("")}</div>${cs.length>1?`<div class="acc-dots">${cs.map((_,i)=>`<i class="${i?"":"on"}"></i>`).join("")}</div><p class="acc-swipe">Arraste para o lado para ver o outro cartão ›</p>`:""}</div>`;
}
function slideDots(track){const i=Math.round(track.scrollLeft/track.clientWidth);track.parentElement.querySelectorAll(".acc-dots i").forEach((d,k)=>d.classList.toggle("on",k===i));}
function renderAccCard(){
  const box=document.getElementById("acc-card");if(!box)return;
  if(ACC&&ACC.loyalty&&ACC.loyalty.length)box.innerHTML=sliderHtml(ACC.loyalty,true);
  else if(!ACC&&perks().length)box.innerHTML=`<div class="acc-card invite"><span class="ic" aria-hidden="true">🎁</span><div class="acc-txt"><b>Crie seu cadastro e ganhe</b><small>${perks().map(esc).join("<br>")}</small></div><button class="btn-red" onclick="openAccount('cadastro')">Criar cadastro</button></div>`;
  else box.innerHTML="";
}
function openAccount(tab){
  document.getElementById("md").innerHTML=ACC?accountView():authView(tab||"entrar");
  document.getElementById("ovl").classList.add("on");
}
function authView(tab){
  const reg=tab==="cadastro";
  return `<button class="x" onclick="closeModal()" aria-label="Fechar">×</button><div class="t"><h2>${reg?"Criar cadastro":"Entrar"}</h2><p>Só com seu telefone e uma senha de 4 a 6 números.</p></div>
  <form class="body ck" id="accf" onsubmit="return accSubmit(event,'${reg?"cadastro":"entrar"}')">
    ${reg&&perks().length?`<div class="perks">🎁 ${perks().map(esc).join("<br>🍕 ")}</div>`:""}
    ${reg?`<label>Nome<input name="name" required autocomplete="name"></label>`:""}
    <label>Telefone / WhatsApp<input name="phone" type="tel" required autocomplete="tel"></label>
    <label>${reg?"Crie uma senha (4 a 6 números)":"Senha"}<input name="pin" type="password" inputmode="numeric" pattern="[0-9]{4,6}" maxlength="6" required autocomplete="${reg?"new-password":"current-password"}"></label>
    ${reg?`<label>Repita a senha<input name="pin2" type="password" inputmode="numeric" pattern="[0-9]{4,6}" maxlength="6" required autocomplete="new-password"></label>`:""}
    <p class="acc-err" id="acc-err" role="alert"></p>
    <p class="acc-switch">${reg?`Já tem cadastro? <a href="#" onclick="openAccount('entrar');return false">Entrar</a>`:`Ainda não tem? <a href="#" onclick="openAccount('cadastro');return false">Criar cadastro</a>`}</p>
    ${reg?`<p class="privacy">Usamos seu nome e telefone só para os seus pedidos e a fidelidade.</p>`:`<p class="privacy">Esqueceu a senha? Peça uma nova para a pizzaria pelo WhatsApp.</p>`}
  </form><div class="ft"><button class="bk" type="button" onclick="backFromLogin()">‹ Voltar</button><button class="nx" type="submit" form="accf">${reg?"Criar cadastro":"Entrar"}</button></div>`;
}
function backFromLogin(){const fn=AFTER_LOGIN;AFTER_LOGIN=null;if(fn)fn();else closeModal();}
async function accSubmit(ev,mode){
  ev.preventDefault();const f=ev.target,err=document.getElementById("acc-err");err.textContent="";
  if(mode==="cadastro"&&f.pin.value!==f.pin2.value){err.textContent="As duas senhas não são iguais.";return false;}
  const btn=document.querySelector(".md .ft .nx");btn.disabled=true;
  const j=await accApi("/"+mode,mode==="cadastro"?{name:f.name.value,phone:f.phone.value,pin:f.pin.value}:{phone:f.phone.value,pin:f.pin.value});
  btn.disabled=false;
  if(!j.ok){err.textContent=j.error||"Não deu certo. Tente de novo.";return false;}
  setAcc(j);toast(mode==="cadastro"?"Cadastro criado!":`Olá, ${ACC.name.split(" ")[0]}!`);
  if(AFTER_LOGIN){const fn=AFTER_LOGIN;AFTER_LOGIN=null;fn();}else openAccount();
  return false;
}
function accountView(){
  const a=ACC,cs=a.loyalty||[];
  return `<button class="x" onclick="closeModal()" aria-label="Fechar">×</button><div class="t"><h2>Olá, ${esc(a.name.split(" ")[0])}!</h2><p>${esc(a.phone)}</p></div><div class="body acc">
    ${a.first_order?`<div class="perks">🎉 Você tem <b>${esc(a.first_order)}</b>. Já sai no seu próximo pedido.</div>`:""}
    ${cs.length?`<h3>Cartões fidelidade</h3>${sliderHtml(cs,false)}${cs.filter(l=>l.rewards).map(l=>`<p class="gift-note">🎁 Você ganhou <b>${l.rewards>1?l.rewards+" × ":""}${esc(l.reward_text)}</b>. Sabores: ${l.flavors.map(esc).join(", ")}. Ponha na cesta e marque “usar” ao finalizar.</p>`).join("")}`:""}
    <h3>Meus pedidos</h3>
    ${a.orders.length?a.orders.map(o=>`<div class="hist"><div class="hl"><b>#${o.id}</b> · ${esc(o.date)}<small>${o.items.map(esc).join(", ")}</small></div><div class="hr"><span class="st st-${esc(o.status_code)}">${esc(o.status)}</span><b>${money(o.total)}</b>${o.track_url?`<a href="${o.track_url}">Acompanhar ›</a>`:""}</div></div>`).join(""):`<p class="empty-h">Seus pedidos vão aparecer aqui.</p>`}
    ${pushAccountHtml()}
    <details class="pinchg"><summary>Trocar senha</summary><form onsubmit="return pinChange(event)"><label>Senha atual<input name="pin" type="password" inputmode="numeric" maxlength="6" required></label><label>Senha nova (4 a 6 números)<input name="new_pin" type="password" inputmode="numeric" pattern="[0-9]{4,6}" maxlength="6" required></label><button class="btn-red">Trocar senha</button></form></details>
  </div><div class="ft"><button class="bk" onclick="accLogout()">Sair</button><button class="nx" onclick="closeModal()">Ver cardápio</button></div>`;
}
async function pinChange(ev){ev.preventDefault();const f=ev.target;const j=await accApi("/senha",{pin:f.pin.value,new_pin:f.new_pin.value});if(!j.ok){toast(j.error);return false;}setAcc(j);toast("Senha trocada.");openAccount();return false;}
async function accLogout(){await accApi("/sair",{});setAcc(null);closeModal();toast("Você saiu da sua conta.");}
// prêmio: pizza da categoria/tamanho do cartão, só com sabores liberados pelo dono
function rewardFits(l,catId,label,ids){return catId===l.category_id&&(!l.size||label===l.size)&&ids.every(id=>l.product_ids.includes(id));}
function rewardItems(l){return cart.map((i,idx)=>({i,idx})).filter(({i})=>rewardFits(l,i.sel.category_id,i.variant,i.sel.flavors));}
function rewardTag(card,pid){return !!(ACC&&(ACC.loyalty||[]).some(l=>l.rewards>0&&rewardFits(l,card.cat.id,card.label,[pid])));}
function ckAccount(){
  if(ACC){
    const cs=(ACC.loyalty||[]).filter(l=>l.rewards>0);
    return `<div class="acc-line"><b>✓ Pedido no cadastro de ${esc(ACC.name.split(" ")[0])}</b>${ACC.first_order?`<span>🎉 ${esc(ACC.first_order)}</span>`:""}
      ${cs.map(l=>rewardItems(l).length?`<label class="use-reward"><input type="checkbox" class="use-reward-cb" data-id="${l.id}" onchange="totals()" checked> Usar ${esc(l.reward_text)}</label>`
        :`<span class="hint">🎁 Você tem ${esc(l.reward_text)}: ponha na cesta 1 pizza ${esc(l.name)}${l.size?" "+esc(l.size):""} de um destes sabores: ${l.flavors.map(esc).join(", ")}.</span>`).join("")}</div>`;
  }
  return perks().length?`<div class="acc-line invite"><span>🎁 Com cadastro você ganha: ${perks().map(esc).join(" · ")}</span><span class="acc-links"><a href="#" onclick="AFTER_LOGIN=openCheckout;openAccount('cadastro');return false">Criar cadastro</a> · <a href="#" onclick="AFTER_LOGIN=openCheckout;openAccount('entrar');return false">Entrar</a></span></div>`:"";
}
function usedRewards(){return [...document.querySelectorAll(".use-reward-cb:checked")].map(c=>Number(c.dataset.id));}
function fillAccount(){
  if(!ACC)return;const f=document.getElementById("ckf");
  // os dados guardados no aparelho são de outra pessoa (outro telefone): limpa antes de usar os da conta
  const digits=x=>String(x||"").replace(/\D/g,"").slice(-11);
  if(digits(f.tel.value)!==digits(ACC.phone)){["nome","rua","num","comp","ref"].forEach(k=>{const el=f.querySelector(`[name=${k}]`);if(el)el.value="";});document.getElementById("bairro").value="";}
  f.nome.value=f.nome.value||ACC.name;f.tel.value=ACC.phone;
  const a=ACC.address||{};["rua","num","comp","ref"].forEach(k=>{const el=f.querySelector(`[name=${k}]`);if(el&&!el.value&&a[k])el.value=a[k];});
  const b=document.getElementById("bairro");if(a.bairro&&!b.value&&[...b.options].some(o=>o.value===a.bairro))b.value=a.bairro;
}
// mesma conta do servidor (services/loyalty.py), só para o cliente ver o total antes de enviar
function accDiscount(){
  if(!ACC)return {value:0,note:""};
  let v=0;const notes=[];const s=subtotal();const free={};
  usedRewards().forEach(id=>{
    const l=(ACC.loyalty||[]).find(x=>x.id===id);if(!l)return;
    const opts=rewardItems(l).filter(({i,idx})=>(free[idx]||0)<i.qty);if(!opts.length)return;
    const best=opts.reduce((a,b)=>(b.i.base||0)>(a.i.base||0)?b:a);free[best.idx]=(free[best.idx]||0)+1;v+=best.i.base||0;notes.push(`${l.name} grátis`);
  });
  if(ACC.first_order&&DATA.first_order){const rest=s-v;const off=DATA.first_order.type==="percent"?Math.round(rest*DATA.first_order.value)/100:Math.min(rest,DATA.first_order.value);if(off>0){v+=off;notes.push("1º pedido");}}
  return {value:Math.min(v,s),note:notes.join(" + ")};
}
accApi("").then(setAcc);

/* ---------- app no celular (PWA) e avisos (Web Push) ---------- */
const SLUG=DATA.tenant.slug;
const STANDALONE=window.matchMedia("(display-mode: standalone)").matches||navigator.standalone===true;
const IOS=/iphone|ipad|ipod/i.test(navigator.userAgent);
let SWREG=null, INSTALL_EVT=null, PUSH_ENDPOINT="";
function lsGet(k){try{return localStorage.getItem(k+"_"+SLUG);}catch(e){return null;}}
function lsSet(k,v){try{localStorage.setItem(k+"_"+SLUG,v);}catch(e){}}
if("serviceWorker" in navigator){
  navigator.serviceWorker.register(`/${SLUG}/sw.js`,{scope:`/${SLUG}/`}).then(r=>{SWREG=r;pushSync();}).catch(()=>{});
}
window.addEventListener("beforeinstallprompt",e=>{e.preventDefault();INSTALL_EVT=e;renderAppBar();});
window.addEventListener("appinstalled",()=>{INSTALL_EVT=null;renderAppBar();toast("App instalado! Procure o ícone na tela do celular.");});
function iosNeedsInstall(){return IOS&&!STANDALONE;}
// faixa “Instale o app” acima do cardápio; fechada, volta depois de 7 dias
function renderAppBar(){
  const box=document.getElementById("app-bar");if(!box)return;
  const closed=Number(lsGet("app_bar_fechada")||0);
  if(STANDALONE||(Date.now()-closed<7*864e5)||!(INSTALL_EVT||iosNeedsInstall())){box.innerHTML="";return;}
  box.innerHTML=`<div class="app-bar"><img src="/${SLUG}/icone-96.png" alt="" width="44" height="44"><div class="ab-txt"><b>Instale o app da ${esc(DATA.tenant.name)}</b><small>Peça mais rápido e receba avisos do seu pedido.</small></div><button class="btn-red" onclick="installApp()">Instalar</button><button class="ab-x" onclick="lsSet('app_bar_fechada',String(Date.now()));renderAppBar()" aria-label="Fechar">×</button></div>`;
}
function installApp(){
  if(INSTALL_EVT){INSTALL_EVT.prompt();INSTALL_EVT.userChoice.finally(()=>{INSTALL_EVT=null;renderAppBar();});}
  else showIosHelp();
}
function showIosHelp(forPush){
  document.getElementById("md").innerHTML=`<button class="x" onclick="closeModal()" aria-label="Fechar">×</button><div class="t"><h2>Instalar no iPhone</h2><p>${forPush?"No iPhone, os avisos só funcionam com o app instalado.":"Leva 10 segundos."}</p></div>
  <div class="body ios-help"><ol>
    <li>Abra este site no <b>Safari</b>.</li>
    <li>Toque em <b>Compartilhar</b> <span class="ios-share" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v12M8 7l4-4 4 4M5 11v9h14v-9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span> (o quadrado com a seta, na barra de baixo).</li>
    <li>Role e toque em <b>Adicionar à Tela de Início</b>.</li>
    <li>Toque em <b>Adicionar</b>. Pronto: o ícone da ${esc(DATA.tenant.name)} aparece na tela do celular.</li>
    ${forPush?`<li>Abra o app pelo ícone e toque em <b>Ativar avisos</b>.</li>`:""}
  </ol></div><div class="ft"><button class="nx" onclick="closeModal()">Entendi</button></div>`;
  document.getElementById("ovl").classList.add("on");
}
function canPush(){return !!(DATA.push_key&&SWREG&&"PushManager" in window&&"Notification" in window);}
function pushOn(){return !!PUSH_ENDPOINT&&"Notification" in window&&Notification.permission==="granted";}
function urlB64(s){const p="=".repeat((4-s.length%4)%4);const r=atob((s+p).replace(/-/g,"+").replace(/_/g,"/"));return Uint8Array.from([...r].map(c=>c.charCodeAt(0)));}
async function pushPost(sub,track){
  try{await fetch(`/${SLUG}/api/push`,{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify({subscription:sub.toJSON(),track:track||""})});}catch(e){}
}
async function pushSubscribe(track){
  if(!canPush()){if(iosNeedsInstall())showIosHelp(true);else toast("Este navegador não aceita avisos.");return false;}
  const perm=await Notification.requestPermission();
  if(perm!=="granted"){toast("Avisos bloqueados. Dá para liberar nas configurações do navegador.");return false;}
  try{
    let sub=await SWREG.pushManager.getSubscription();
    if(!sub)sub=await SWREG.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlB64(DATA.push_key)});
    PUSH_ENDPOINT=sub.endpoint;await pushPost(sub,track);
  }catch(e){toast("Não deu para ativar os avisos agora.");return false;}
  toast("Avisos ativados ✓");document.querySelectorAll(".push-ask").forEach(el=>el.remove());return true;
}
// já tinha ativado: guarda o endereço (vai junto no pedido) e liga à conta, se entrou
async function pushSync(){
  if(!canPush())return;
  const sub=await SWREG.pushManager.getSubscription();
  PUSH_ENDPOINT=sub&&Notification.permission==="granted"?sub.endpoint:"";
  if(PUSH_ENDPOINT&&ACC)pushPost(sub);
}
function pushAskHtml(track){
  if(pushOn())return "";
  if(canPush())return `<div class="push-ask"><span>🔔</span><div><b>Quer ser avisado quando sua pizza sair?</b><small>A gente avisa no celular quando o pedido for confirmado e quando sair para entrega.</small></div><button class="btn-red" onclick="pushSubscribe('${esc(track||"")}')">Ativar avisos</button></div>`;
  if(iosNeedsInstall()&&DATA.push_key)return `<div class="push-ask"><span>🔔</span><div><b>Receba avisos do seu pedido</b><small>No iPhone, instale o app para receber os avisos.</small></div><button class="btn-red" onclick="showIosHelp(true)">Como instalar</button></div>`;
  return "";
}
async function pushPrefs(body){
  const j=await fetch(`/${SLUG}/api/push/preferencias`,{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",body:JSON.stringify({endpoint:PUSH_ENDPOINT,...body})}).then(r=>r.json()).catch(()=>({}));
  if(body.off){try{const s=await SWREG.pushManager.getSubscription();if(s)await s.unsubscribe();}catch(e){}PUSH_ENDPOINT="";toast("Avisos desligados.");openAccount();}
  else toast(j.promos?"Você vai receber as promoções.":"Promoções desligadas. Os avisos do pedido continuam.");
}
function pushAccountHtml(){
  if(!DATA.push_key)return "";
  if(pushOn())return `<h3>Avisos no celular</h3><div class="push-prefs"><p>🔔 Avisos do pedido ligados.</p><label class="use-reward"><input type="checkbox" checked onchange="pushPrefs({promos:this.checked})"> Receber promoções</label><button class="link-btn" onclick="pushPrefs({off:true})">Desligar todos os avisos</button></div>`;
  return `<h3>Avisos no celular</h3>${pushAskHtml("")||`<p class="hint">Este navegador não aceita avisos.</p>`}`;
}
renderAppBar();
function openPromos(){
  const md=document.getElementById("md");
  md.innerHTML=`<button class="x" onclick="closeModal()" aria-label="Fechar">×</button><div class="t"><h2>🏷 Promoções de hoje</h2></div><div class="body promos">`+
    PROMOS.map(p=>`<div class="promo-card">${p.image?`<img src="${esc(p.image)}" alt="">`:""}<div class="promo-body"><span class="promo-tag">${esc(p.badge)}</span><h3>${esc(p.name)}</h3>${p.message?`<p>${esc(p.message)}</p>`:""}<p class="promo-rule">${esc(p.text)}</p>
      <button class="btn-red" onclick="closeModal();goCat('${esc(p.category)}')">Ver no cardápio</button></div></div>`).join("")+
    `</div><div class="ft"><button class="bk" style="flex:1" onclick="closeModal()">Fechar</button></div>`;
  document.getElementById("ovl").classList.add("on");
}
(function promoInit(){
  if(!PROMOS.length)return;
  // selo das promoções no topo, junto da conta e do WhatsApp (flutuando, ele tapava o cartão fidelidade)
  const actions=document.querySelector(".hero-actions");
  if(actions)actions.insertAdjacentHTML("afterbegin",`<button type="button" class="hero-promo" onclick="openPromos()" aria-label="Ver promoções"><span aria-hidden="true">🏷</span><b>PROMO</b>${PROMOS.length>1?`<i>${PROMOS.length}</i>`:""}</button>`);
  const key="promos_vistas_"+DATA.tenant.slug, ids=PROMOS.filter(p=>p.popup).map(p=>p.id).join(",");
  let seen=""; try{seen=sessionStorage.getItem(key)||"";}catch(e){}
  if(ids&&seen!==ids){setTimeout(()=>{if(!document.getElementById("ovl").classList.contains("on"))openPromos();},900);try{sessionStorage.setItem(key,ids);}catch(e){}}
})();
