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
const CLOSED=DATA.open===false;
const CLOSED_MSG="Estamos fechados no momento. Confira nossos horários de atendimento.";
(function status(){
  let open=DATA.open;
  if(open===undefined){
    const now=new Date(), d=now.getDay(), m=now.getHours()*60+now.getMinutes();
    const h=DATA.hours[d]; open=false;
    if(h){const [a,b]=h; open = m>=a && m<b;}
  }
  document.getElementById("st-dot").classList.toggle("open",open);
  document.getElementById("st-txt").textContent=open?"Aberto":"Fechado";
  const f=document.getElementById("ft-st"); f.textContent=open?"◉ Aberto!":"◉ Fechado!"; f.classList.toggle("open",open);
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
function catHead(cat){
  const c=cat.raw||{}, w=cat.name.trim().split(/\s+/), top=w.length>1?w[0]:"", big=w.length>1?w.slice(1).join(" "):w[0];
  return `<div class="cat-head acc-${esc(c.accent||"vermelho")}"${c.banner?` style="--photo:url('${esc(c.banner)}')"`:""}>
    <span class="cat-ico" aria-hidden="true">${ICONS[c.icon]||ICONS.fatia}</span>
    <div><h2 class="cat-title">${top?`<span class="top">${esc(top)}</span>`:""}<span class="big">${esc(big)}</span></h2>${c.subtitle?`<p class="cat-sub">${esc(c.subtitle)}</p>`:""}</div></div>`;
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
      cat.cards.push({title:p.name,desc:(p.description||"")+(extras.length?` Acompanha: ${extras.join(", ")}.`:""),fixed:v.price,label:v.label,max:v.max_flavors,cat:c,sizes:Array.from({length:v.max_flavors},(_,i)=>i+1)});
    } else if(c.kind==="bebida"){
      // bebida: um card por item, um botão por tamanho; vai direto para a cesta
      c.products.forEach(p=>cat.cards.push({drink:true,p,cat:c,title:p.name}));
    } else {
      // agrupa por tamanho (variant label)
      const labels=[...new Set(c.products.flatMap(p=>p.variants.map(v=>v.label)))];
      labels.forEach(lb=>{
        const prices=c.products.map(p=>(p.variants.find(v=>v.label===lb)||{}).price).filter(x=>x!=null);
        const maxF=Math.max(...c.products.map(p=>(p.variants.find(v=>v.label===lb)||{}).max_flavors||1));
        cat.cards.push({title:lb,from:Math.min(...prices),label:lb,max:maxF,cat:c,sizes:Array.from({length:maxF},(_,i)=>i+1)});
      });
    }
    CATS.push(cat);
  });
  const sel=document.getElementById("catsel"), box=document.getElementById("cats");
  CATS.forEach((cat,ci)=>{
    sel.insertAdjacentHTML("beforeend",`<option value="${cat.slug}">${esc(cat.name)}</option>`);
    const cards=cat.cards.map((k,ki)=>{
      if(k.notice) return "";
      if(k.drink) return `<div class="card drink" data-name="${esc(k.title)}"><div class="top">${k.p.image?`<img class="th" src="${esc(k.p.image)}" alt="" loading="lazy">`:""}<div><h3>${esc(k.title)}</h3>${k.p.description?`<p class="desc">${esc(k.p.description)}</p>`:""}</div></div><div class="btns">${k.p.variants.map((v,vi)=>`<button onclick="addDrink(${ci},${ki},${vi})">${esc(v.label)}<small>${money(v.price)}</small></button>`).join("")}</div></div>`;
      const btns=k.sizes.map((n,i)=>`<button class="${i===k.sizes.length-1?"main-btn":""}" onclick="startFlow(${ci},${ki},${n})">${n} sabor${n>1?"es":""}</button>`).join("");
      if(k.fixed) return `<div class="card full" data-name="${esc(k.title)}"><div class="top"><div><h3>${esc(k.title)}</h3><p class="desc">${esc(k.desc)}</p><p class="price">${money(k.fixed)}</p></div></div><div class="btns">${btns}</div></div>`;
      return `<div class="card" data-name="${esc(k.title)}"><div class="top"><h3>${esc(k.title)}</h3><span class="from">A partir de <b>${money(k.from)}</b></span></div><div class="btns">${btns}</div></div>`;
    }).join("");
    if(cat.kind==="notice"){box.insertAdjacentHTML("beforeend",`<section class="cat" id="cat-${cat.slug}" data-slug="${cat.slug}"><div class="notice"><span class="notice-ico" aria-hidden="true">!</span><div><h2>Recados</h2>${cat.cards[0].lines.map(l=>`<p>${esc(l)}</p>`).join("")}</div></div></section>`);return;}
    box.insertAdjacentHTML("beforeend",`<section class="cat" id="cat-${cat.slug}" data-slug="${cat.slug}">${catHead(cat)}<div class="grid">${cards}</div></section>`);
  });
})();
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
function closeModal(){document.getElementById("ovl").classList.remove("on");F=null;}
function flavorPool(){
  const k=F.card;
  if(k.cat.kind==="metro"){const src=comboOf(k.cat).sources;return DATA.categories.filter(c=>c.kind!=="metro"&&src.includes(c.slug)).flatMap(c=>c.products.map(p=>({...p,price:k.fixed,fixed:true})));}
  return k.cat.products.map(p=>{const v=p.variants.find(v=>v.label===k.label);return v?{...p,price:v.price}:null;}).filter(Boolean);
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
    body=`<input class="srch" placeholder="Busque por um sabor" value="${esc(F.q||"")}" oninput="F.q=this.value;fl(this.value)"><div id="fl">`+flavorPool().map((p,pi)=>`<div class="opt ${cur&&cur.name===p.name?"sel":""}" data-n="${esc(p.name.toLowerCase())}" onclick="pickFlavor(${pi})">${p.image?`<img class="th" src="${esc(p.image)}" alt="" loading="lazy">`:""}<div class="grow"><div class="n">${esc(p.name)}</div><div class="d">${esc(p.description||"")}</div>${p.fixed?"":`<div class="p">${money(p.price)}</div>`}</div></div>`).join("")+`</div>`;
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
    cart.push({sel,title,variant:k.label,border:F.border!=null?borderLabel(DATA.borders[F.border]):"",addons:Object.entries(F.addons).map(([i,q])=>`${q}x ${DATA.addons[i].name}`).join(", "),extras:comboExtras(),notes:F.notes.trim(),price:unitPrice(),qty:F.qty});
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
  md.innerHTML=`<button class="x" onclick="closeModal()">×</button><div class="t"><h2>Finalizar pedido</h2><p>Pagamento na entrega. O pedido é enviado pelo WhatsApp.</p></div>
  <form class="body ck" id="ckf" onsubmit="return finish(event)">
    <label>Nome<input name="nome" required></label>
    <label>Telefone / WhatsApp<input name="tel" type="tel" required></label>
    <label style="display:flex;align-items:center;gap:8px;margin-top:12px"><input type="checkbox" id="ck-wd" style="width:18px;height:18px;margin:0" ${wd?"checked":""} onchange="document.getElementById('addr').style.display=this.checked?'none':'';totals()"> Retirar na loja</label>
    <div id="addr" style="${wd?"display:none":""}">
      <label>Rua<input name="rua"></label>
      <div class="r2"><label>Número<input name="num"></label><label>Complemento<input name="comp"></label></div>
      <label>Bairro<select name="bairro" id="bairro" onchange="totals()"><option value="">Selecione…</option>${DATA.neighborhoods.map(n=>`<option value="${esc(n.name)}">${esc(n.name)} — ${money(n.fee)}</option>`).join("")}<option value="__outro__">Outro bairro (taxa a confirmar)</option></select></label>
      <label>Ponto de referência<input name="ref"></label>
    </div>
    <label>Forma de pagamento<select name="pag" id="pag" required onchange="document.getElementById('troco').style.display=this.value==='Dinheiro'?'':'none'"><option value="">Selecione…</option>${DATA.tenant.accepted_payments.split(",").filter(p=>p.trim()).map(p=>`<option>${esc(p.trim())}</option>`).join("")}</select></label>
    <label id="troco" style="display:none">Troco para quanto? (opcional)<input name="troco" type="number" step="0.01" min="0"></label>
    <div class="sum" id="sum"></div>
    <p class="privacy">Usamos seu nome, telefone e endereço só para entregar e falar sobre o seu pedido.</p>
  </form>
  <div class="ft"><button class="bk" type="button" onclick="openCart()">‹ Voltar</button><button class="nx" type="submit" form="ckf" style="background:#25d366">Enviar pelo WhatsApp</button></div>`;
  document.getElementById("ovl").classList.add("on");fillRemembered();totals();
}
// nome, telefone e endereço ficam salvos só neste aparelho, para o próximo pedido ser mais rápido
const REMEMBER_KEY="snep_cliente_"+DATA.tenant.slug;
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
function totals(){const f=fee(),s=subtotal();document.getElementById("sum").innerHTML=`<div><span>Subtotal</span><span>${money(s)}</span></div><div><span>Entrega</span><span>${f===null?"a confirmar":money(f)}</span></div><div class="tt"><span>Total${f===null?" (sem entrega)":""}</span><span>${money(s+(f||0))}</span></div>`;}
function finish(ev){
  ev.preventDefault();const f=ev.target,wd=document.getElementById("ck-wd").checked;
  if(!wd&&(!f.rua.value||!f.num.value||!f.bairro.value)){toast("Preencha o endereço de entrega.");return false;}
  const payload={withdraw:wd,customer_name:f.nome.value,customer_phone:f.tel.value,street:wd?"":f.rua.value,number:wd?"":f.num.value,complement:wd?"":f.comp.value,
    neighborhood:wd?"":(f.bairro.value==="__outro__"?"":f.bairro.value),reference:wd?"":f.ref.value,payment_method:f.pag.value,change_for:f.troco.value||null,
    items:cart.map(i=>({...i.sel,notes:i.notes,quantity:i.qty,title:i.title,border:i.border,addons_text:i.addons,extras_text:i.extras,unit_price:i.price}))};
  const btn=document.querySelector(".md .ft .nx");btn.disabled=true;btn.textContent="Enviando…";
  fetch(DATA.order_url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)})
    .then(r=>r.json()).then(r=>{
      if(!r.ok){toast(r.error||"Erro ao enviar pedido.");btn.disabled=false;btn.textContent="Enviar pelo WhatsApp";return;}
      document.getElementById("md").innerHTML=`<button class="x" onclick="closeModal()">×</button><div class="body succ"><h3>Pedido pronto! 🍕</h3>${r.order_id?`<p>Pedido <b>#${r.order_id}</b> · Total ${money(r.total)}${r.delivery_fee===null?" + entrega a confirmar":""}</p>`:""}${r.eta?`<p class="eta-box">${r.eta_label}: <b>${r.eta}</b></p>`:""}<p>Clique abaixo para abrir o WhatsApp com o pedido preenchido e enviar para a pizzaria.</p><a class="btn-red btn-wa" style="display:block;padding:14px;font-size:16px" href="${r.wa_link}" target="_blank" rel="noopener">Abrir WhatsApp</a></div><div class="ft"><button class="bk" style="flex:1" onclick="closeModal()">Fechar</button></div>`;
      remember(payload);cart=[];renderCart();
    }).catch(()=>{toast("Falha de conexão. Tente novamente.");btn.disabled=false;btn.textContent="Enviar pelo WhatsApp";});
  return false;
}
renderCart();
