"use strict";

const $ = (id) => document.getElementById(id);
const clean = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
const euro = (n) => n === null || n === undefined ? "—" : new Intl.NumberFormat("de-DE", {style:"currency",currency:"EUR"}).format(n);
const state = {schema:null,cases:[],caseId:null,extra:{},result:null,runId:null,selectedNode:null};
const statusGerman = {SATISFIED:"Erfüllt", NOT_SATISFIED:"Nicht erfüllt",UNKNOWN:"Unbekannt",CONFLICTED:"Widersprüchlich",
  READY_FOR_EXPERT_REVIEW:"Zur Fachprüfung", INELIGIBLE_SELECTED_PATH:"Gewählter Pfad gesperrt",EVIDENCE_REQUIRED:"Nachweise fehlen",CONFLICTED_EVIDENCE:"Widersprüchliche Belege"};
function spanStatus(status){return `<span class="status ${clean(status)}">${clean(statusGerman[status]||status)}</span>`;}
async function api(path, options={}) {
  const response=await fetch(path,{...options,headers:{"Content-Type":"application/json",...(options.headers||{})}});
  if(!response.ok){let msg;try{const data=await response.json();msg=data.detail;}catch{msg=response.statusText;}throw new Error(msg||`HTTP ${response.status}`);}
  return response.json();
}
function err(msg){$('errorBox').textContent=msg||'';$('errorBox').classList.toggle('hidden',!msg);}
function option(text,value){const e=document.createElement('option');e.textContent=text;e.value=value;return e;}
function setField(key,value,verification='confirmed',ref='SYNTHETISCH: ergänzte Fallannahme') {
  const input=$(`field-${key}`), verify=$(`verification-${key}`),evidence=$(`evidence-${key}`);
  if(!input||!verify||!evidence)return;
  if(input.tagName==='SELECT')input.value=value===true?'true':value===false?'false':value??'';
  else input.value=value??'';
  verify.value=verification;evidence.value=verification==='confirmed'?ref:'';
}
function clearFields(){document.querySelectorAll('[data-fact]').forEach(el=>{el.value=el.id.startsWith('verification-')?'unknown':'';});err('');}
function demo() {
  clearFields();
  const presets={transaction_type:'ausgliederung',registered_merchant:true,liabilities_not_exceed_assets:true,
    recipient_eu_eea:true,contributor_eu_eea:true,german_tax_right_received_shares:true,
    registration_effective:true,register_entry_date:'2026-02-01',
    retroactive_requested:true,tax_transfer_date:'2025-12-31',register_filing_date:'2026-01-01',
    profit_method:'bilanz',valuation_choice:'buchwert',intermediate_value:250000,transfer_costs:0,
    withdrawals:0,contributions:0,event_type:'keines'};
  for(const [key,val] of Object.entries(presets))setField(key,val);
  err('Synthetische Annahmen eingesetzt. Datums- und Gegenleistungswerte sind Demonstrationsdaten, keine geprüften Mandantennachweise.');
}
function fieldsForm(){
  const root=$('fields');root.textContent='';
  let group=null,block=null;
  for(const field of state.schema.fields){
    if(field.group!==group){group=field.group;block=document.createElement('div');block.className='group';
      const title=document.createElement('h3');title.textContent=group;block.append(title);root.append(block);}
    const wrap=document.createElement('div');wrap.className='field';
    const lab=document.createElement('label');lab.textContent=field.label;lab.htmlFor=`field-${field.key}`;wrap.append(lab);
    const line=document.createElement('div');line.className='fact-row';
    let val;
    if(field.type==='bool'||field.type==='choice'){
      val=document.createElement('select');val.append(option('Unbekannt',''));
      if(field.type==='bool'){val.append(option('Ja','true'),option('Nein','false'));}
      else for(const choice of field.choices)val.append(option(choice==='ausgliederung'?'Ausgliederung':choice==='einzelrechtsnachfolge'?'Einzelrechtsnachfolge':choice.replaceAll('_',' '),choice));
    } else {
      val=document.createElement('input');val.placeholder=field.type==='money'?'EUR-Betrag':field.type==='fraction'?'z. B. 0,5':field.type==='date'?'JJJJ-MM-TT':'';
      if(field.type==='date')val.type='date';
      else if(['money','fraction'].includes(field.type)){val.type='number';val.step=field.type==='money'?'0.01':'0.01';val.min='0';}
    }
    val.id=`field-${field.key}`;val.dataset.fact=field.key;line.append(val);
    const verified=document.createElement('select');verified.id=`verification-${field.key}`;verified.dataset.fact=field.key;
    verified.append(option('Unbekannt','unknown'),option('Ungeprüft','reported'),option('Bestätigt','confirmed'));line.append(verified);
    wrap.append(line);
    const evidence=document.createElement('input');evidence.className='evidence';evidence.id=`evidence-${field.key}`;
    evidence.placeholder='Nachweisreferenz / Aktenvermerk (bei „Bestätigt“)';evidence.dataset.fact=field.key;
    wrap.append(evidence);block.append(wrap);
  }
}
function collect(){
  const out={};
  for(const f of state.schema.fields){
    const v=$(`field-${f.key}`).value;
    const verification=$(`verification-${f.key}`).value;
    const evidence=$(`evidence-${f.key}`).value.trim();
    if(!v && !evidence && verification==='unknown')continue;
    if(verification==='confirmed'&&(!evidence||v===''))throw Error(`${f.label}: Bestätigt benötigt Wert und Nachweisreferenz.`);
    let value=v||null;
    if(v!==''){
      if(f.type==='bool')value=(v==='true');
      else if(f.type==='money'||f.type==='fraction')value=Number(v);
    }
    out[f.key]={value,verification,evidence_ref:evidence};
  }
  return out;
}
function metric(label,value){return `<div class="stat"><span class="muted">${clean(label)}</span><strong>${clean(value)}</strong></div>`;}
function populateReport(doc){
  state.result=doc.report;state.runId=doc.run_id;err('');
  const r=doc.report; $('outcome').classList.remove('hidden');
  for(const field of state.schema.fields){
    const stored=r.facts[field.key];
    if(stored)setField(field.key,stored.value,stored.verification,stored.evidence_ref||'');
  }
  const integrity=(doc.verification||{});
  $('integrity').textContent=integrity.valid?'Hash + Replay korrekt':'Audit nicht bestätigt';
  $('integrity').style.color=integrity.valid?'#17633b':'#a53026';
  $('resultIntro').innerHTML=`${spanStatus(r.selected.overall)} <span class="muted">Lauf ${clean(doc.run_id)} · Normstand ${clean(r.law_as_of)} · ${r.assessments.length} Prüfungen</span>`+
    (doc.current_case_facts_match===false?'<p class="error">Historischer Prüflauf: Die ursprünglichen Fallfakten haben sich verändert. Bitte erneut ausführen.</p>':'');
  $('metrics').innerHTML=metric('Bewertungsmodus',r.selected.mode||'—')+metric('Ungeklärte Kriterien',r.open_checks.length)+
    metric('Nicht erfüllte Kriterien',r.failed_checks.length)+metric('Graph Nodes / Edges',`${r.graph.nodes.length} / ${r.graph.edges.length}`);
  $('assessments').innerHTML=`<table><thead><tr><th>Schritt</th><th>Status</th><th>Begründung</th></tr></thead><tbody>`+
    r.assessments.map(a=>`<tr class="assessment" data-assess="${clean(a.code)}"><td><strong>${clean(a.label)}</strong><br><span class="muted">${clean(a.code)}</span></td><td>${spanStatus(a.status)}</td><td>${clean(a.reason)}<br><span class="muted">${a.legal_ids.map(clean).join(' · ')}</span></td></tr>`).join('')+'</tbody></table>';
  document.querySelectorAll('[data-assess]').forEach(el=>el.addEventListener('click',()=>{activate('graph');selectNode(`ASSESS:${el.dataset.assess}`);}));
  $('taxReport').innerHTML=`<h3>Wertansatz: Buchwert / Zwischenwert / Gemeiner Wert</h3><div class="table-scroll"><table><thead><tr><th>Modus</th><th>Prüfung</th><th>Ansatz</th><th>Vorl. Gewinn</th><th>Neue Anteile AK</th></tr></thead><tbody>`+
    r.valuation_options.map(o=>`<tr><td>${clean(o.mode)}</td><td>${spanStatus(o.status)}</td><td>${euro(o.transferred_tax_value)}</td><td>${euro(o.valuation_gain_preliminary)}</td><td>${euro(o.new_share_cost_basis_preliminary)}</td></tr>`).join('')+
    `</tbody></table></div><h3>Schritt 0: Ohne UmwStG (vereinfachte Referenz)</h3><p>${euro(r.baseline.gain)} · ${clean(r.baseline.type)} · keine Steuerberechnung</p>`+
    `<h3>Schritt 4–5: Folgen je Steuersubjekt</h3><div class="table-scroll"><table><thead><tr><th>Subjekt / Jahr</th><th>Wert / Gewinn</th><th>Hinweis</th></tr></thead><tbody>`+
    r.consequences.map(c=>`<tr><td><strong>${clean(c.entity)}</strong><br>${clean(c.year||'Stichtag offen')}</td><td>${c.tax_basis!==undefined?euro(c.tax_basis):euro(c.gross_gain_preliminary)}</td><td>${clean(c.afa_treatment||c.section16_4_34)}<br><span class="muted">Anteils-AK: ${euro(c.new_share_cost_basis_preliminary)}</span></td></tr>`).join('')+`</tbody></table></div>`+
    `<h3>Schritt 6: Sperrfrist und Veräußerung</h3><p>Einbringungsgewinn I: <strong>${euro(r.sperrfrist.einbringungsgewinn_I)}</strong> · Status ${clean(r.sperrfrist.status)} · Nachträgliche Anteils-AK: ${euro(r.sperrfrist.additional_share_acquisition_costs)}</p>`+
    `<p class="muted">Separater Anteilsveräußerungsgewinn (nur Illustration, keine §17-Freigabe): ${euro(r.sperrfrist.share_sale_gain_preliminary)}</p>`+
    `<h3>Nachweise nach § 22 Abs. 3 UmwStG</h3><div class="table-scroll"><table><thead><tr><th>Zeitjahr</th><th>Stichtag</th><th>Frist</th><th>Nachweisstand</th></tr></thead><tbody>`+
    r.proof_obligations.map(p=>`<tr><td>${p.period}</td><td>${clean(p.reference_date)}</td><td>${clean(p.deadline)}</td><td>${clean(p.due_relative_to_as_of)} · ${clean(p.filing_state)}</td></tr>`).join('')+`</tbody></table></div>`+
    `<h3>Prüfgrenzen &amp; offene Rechtsfolgen</h3><div class="notice">${r.warnings.map(w=>`<p>${clean(w)}</p>`).join('')}</div>`;
  initGraphView();activate('pruefschema');
}
function activate(view){
  document.querySelectorAll('.report-view').forEach(p=>p.classList.toggle('hidden',p.id!==`view-${view}`));
  document.querySelectorAll('.tab').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view===view)));
}
function initGraphView(){
  const graph=state.result.graph;
  $('graphInfo').textContent=`${graph.nodes.length} persistierte Graph-Knoten, ${graph.edges.length} reale Beziehungen. Klick auf Knoten → direkte Abhängigkeiten und Nachweise.`;
  const types=[...new Set(graph.nodes.map(n=>n.kind))].sort();
  $('nodeType').replaceChildren(option('Alle Knotentypen',''),...types.map(t=>option(t,t)));
  $('nodeSearch').value='';renderNodes();
  selectNode('ASSESS:ELIGIBILITY');
}
function renderNodes(){
  if(!state.result)return;
  const q=$('nodeSearch').value.toLowerCase(),kind=$('nodeType').value;
  const nodes=state.result.graph.nodes.filter(n=>(!kind||n.kind===kind)&&(!q||(n.id+' '+n.label).toLowerCase().includes(q)));
  $('nodeList').innerHTML=`<table><thead><tr><th>ID</th><th>Typ</th><th>Status</th></tr></thead><tbody>`+
    nodes.map(n=>`<tr class="graphrow" data-node="${clean(n.id)}"><td><strong>${clean(n.label)}</strong><br><span class="muted">${clean(n.id)}</span></td><td>${clean(n.kind)}</td><td>${clean(n.data.status||'—')}</td></tr>`).join('')+`</tbody></table>`;
  document.querySelectorAll('[data-node]').forEach(el=>el.addEventListener('click',()=>selectNode(el.dataset.node)));
}
function svgElement(name,attrs={},text=''){
  const el=document.createElementNS('http://www.w3.org/2000/svg',name);
  for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);
  if(text)el.textContent=text;
  return el;
}
function selectNode(nodeId){
  const g=state.result?.graph;if(!g)return;
  const node=g.nodes.find(n=>n.id===nodeId);if(!node)return;
  state.selectedNode=nodeId;
  $('inspectorName').textContent=`${node.kind} · ${node.label}`;
  const incoming=g.edges.filter(e=>e.target===nodeId),outgoing=g.edges.filter(e=>e.source===nodeId);
  const byId=Object.fromEntries(g.nodes.map(n=>[n.id,n]));
  const neighbors=$('neighbors');neighbors.replaceChildren();
  const defs=svgElement('defs');const marker=svgElement('marker',{id:'head',markerWidth:6,markerHeight:6,refX:5,refY:3,orient:'auto'});
  marker.append(svgElement('path',{d:'M0,0 L6,3 L0,6 Z',fill:'#7896a4'}));defs.append(marker);neighbors.append(defs);
  function box(n,x,y,central=false){
    neighbors.append(svgElement('rect',{x,y,width:150,height:35,rx:5,class:central?'central':''}));
    neighbors.append(svgElement('text',{x:x+75,y:y+14,'text-anchor':'middle'},n.kind));
    neighbors.append(svgElement('text',{x:x+75,y:y+27,'text-anchor':'middle'},n.label.slice(0,22)));
  }
  const inc=incoming.slice(0,4),out=outgoing.slice(0,4);
  inc.forEach((e,i)=>{
    const x=8+i*184;box(byId[e.source],x,16);
    neighbors.append(svgElement('line',{x1:x+75,y1:51,x2:370,y2:103,'marker-end':'url(#head)'}));
  });
  box(node,295,105,true);
  out.forEach((e,i)=>{
    const x=8+i*184;neighbors.append(svgElement('line',{x1:370,y1:140,x2:x+75,y2:208,'marker-end':'url(#head)'}));box(byId[e.target],x,208);
  });
  const fmtEdge=e=>`<button data-inspect="${clean(e.source===nodeId?e.target:e.source)}">${clean(e.relation)} → ${clean((byId[e.source===nodeId?e.target:e.source]||{}).label||'Unbekannt')}</button>`;
  $('inspectorDetails').innerHTML=`<p class="muted">${clean(node.id)} · ${incoming.length} eingehende / ${outgoing.length} ausgehende Kanten. Im Diagramm max. vier je Richtung.</p>`+
    `<h3>Eingehende Kanten</h3><div class="auditlinks">${incoming.map(fmtEdge).join('')||'Keine'}</div>`+
    `<h3>Ausgehende Kanten</h3><div class="auditlinks">${outgoing.map(fmtEdge).join('')||'Keine'}</div>`+
    `<h3>Persistierte Node-Daten</h3><pre>${clean(JSON.stringify(node.data,null,2))}</pre>`;
  $('inspectorDetails').querySelectorAll('[data-inspect]').forEach(b=>b.addEventListener('click',()=>selectNode(b.dataset.inspect)));
}
async function loadLatest(){
  if(!state.caseId)return;
  try{populateReport(await api(`/api/cases/${encodeURIComponent(state.caseId)}/fachpruefung/latest`));}
  catch(e){if(!String(e.message).includes('Noch keine'))err(e.message);}
}
async function start(){
  try{
    state.schema=await api('/api/fachpruefung/schema');
    const res=await api('/api/cases');state.cases=res.cases.filter(c=>c.synthetic);
    $('caseSelect').replaceChildren(...state.cases.map(c=>option(c.title,c.id)));
    const requested=new URLSearchParams(location.search).get('case');
    state.caseId=state.cases.find(c=>c.id===requested)?.id||state.cases[0]?.id;
    if(state.caseId)$('caseSelect').value=state.caseId;
    fieldsForm();await loadLatest();
    $('caseSelect').addEventListener('change',async()=>{state.caseId=$('caseSelect').value;state.runId=null;
      state.result=null;$('outcome').classList.add('hidden');$('integrity').textContent='Noch kein Lauf';clearFields();await loadLatest();});
    $('reviewForm').addEventListener('submit',async(e)=>{e.preventDefault();err('');const btn=$('submitBtn');btn.disabled=true;
      try{const data=await api(`/api/cases/${encodeURIComponent(state.caseId)}/fachpruefung`,{
        method:'POST',body:JSON.stringify({extra_facts:collect()})});populateReport(data);
      }catch(error){err(error.message);}finally{btn.disabled=false;}});
    $('demoBtn').addEventListener('click',demo);$('clearBtn').addEventListener('click',clearFields);
    $('exportBtn').addEventListener('click',()=>{if(!state.runId)return;
      location.href=`/api/cases/${encodeURIComponent(state.caseId)}/fachpruefung/${encodeURIComponent(state.runId)}/export`;});
    $('loadLatestBtn').addEventListener('click',loadLatest);
    $('nodeSearch').addEventListener('input',renderNodes);$('nodeType').addEventListener('change',renderNodes);
    document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>activate(b.dataset.view)));
  }catch(e){err(e.message);}
}
start();
