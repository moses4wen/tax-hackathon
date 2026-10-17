'use strict';
(() => {
const $=id=>document.getElementById(id);
const h=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=x=>x==null?'Nicht belegt':new Intl.NumberFormat('de-DE',{style:'currency',currency:'EUR'}).format(x);
const S={schema:null,processes:[],process:null,cases:[],case:null,inputs:null,run:null,dirty:false,node:'start'};
const states={READY_FOR_EXPERT_REVIEW:'Fachliche Freigabe offen',FAIR_VALUE_ALTERNATIVE:'Gemeinen Wert gesondert w\u00e4hlen',MODEL_REVIEW_REQUIRED:'Prozesswissen erweitern',DATE_CORRECTION_REQUIRED:'Stichtag korrigieren',EVIDENCE_REQUIRED:'Nachweise fehlen',CONFLICTED_EVIDENCE:'Widerspruch kl\u00e4ren',OTHER_CLASSIFICATION:'Andere Einordnung pr\u00fcfen',MANUAL_REVIEW:'Fachentscheidung erforderlich',INCOMPLETE_OR_INELIGIBLE_PATH:'Unvollst\u00e4ndiger Pr\u00fcfpfad'};
const outcome={yes:'Ja',no:'Nein',unknown:'Unbekannt',conflicted:'Widerspruch',always:'Weiter'};
const can=cap=>!!S.schema?.capabilities[cap];
async function api(path,options={}){
 const r=await fetch(path,{credentials:'same-origin',headers:{'Content-Type':'application/json'},...options});
 const data=await r.json().catch(()=>({detail:'Antwort nicht lesbar'}));
 if(!r.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;
}
function err(e){$('error').textContent=e.message;$('error').hidden=false;}
function toast(t){$('toast').textContent=t;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,6000);}
function safe(fn){return async e=>{try{$('error').hidden=true;await fn(e);}catch(x){err(x);}};}
function tab(id){document.querySelectorAll('.tabview').forEach(e=>e.hidden=e.id!==id);document.querySelectorAll('[data-tab]').forEach(e=>e.classList.toggle('active',e.dataset.tab===id));}
async function processes(selectId){
 S.processes=(await api('/api/functional/processes')).processes;
 $('processList').innerHTML=S.processes.map(p=>`<button class="processItem ${p.id===selectId?'active':''}" data-process="${h(p.id)}"><strong>${h(p.label)}</strong><small>v${p.version} \u00b7 ${p.status==='published'?'Ver\u00f6ffentlicht':'Entwurf'}</small></button>`).join('');
 $('processList').querySelectorAll('button').forEach(b=>b.onclick=safe(()=>selectProcess(b.dataset.process)));
 if(selectId||S.processes.length)await selectProcess(selectId||S.processes.find(p=>p.status==='published')?.id||S.processes[0].id);
}
async function selectProcess(id){
 S.process=await api('/api/functional/processes/'+encodeURIComponent(id));S.run=null;$('result').hidden=true;
 $('processList').querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.process===id));
 const p=S.process, cov=p.coverage;
 $('processTitle').textContent=p.label;$('processMeta').textContent=`VERSION ${p.version} / ${p.id}`;$('processStatus').textContent=p.status==='published'?'Ver\u00f6ffentlicht':'Entwurf';
 $('sourceNotice').textContent=p.definition.source.complete?'Vollst\u00e4ndiger Quell-Snapshot gespeichert. Lokale rechtliche Normalisierungen sind getrennt dokumentiert; Import ist keine Rechtsfreigabe.':'17 beobachtete Quellknoten sind funktional angebunden. Vollst\u00e4ndige Remote-Edges wurden noch nicht verifiziert. Die hier ausgef\u00fchrten Kanten sind eine lokale, explizit normalisierte Prozessdefinition.';
 $('metrics').innerHTML=[[cov.bound_source_nodes,'angebundene Quellknoten'],[cov.local_nodes,'ausf\u00fchrbare Knoten'],[cov.local_edges,'bedingte Kanten'],[p.definition.ruleset,'fixierte Regelversion']].map(([v,l])=>`<div class="metric"><strong>${h(v)}</strong><span>${h(l)}</span></div>`).join('');
 $('definition').value=JSON.stringify(p.definition,null,2);$('definition').readOnly=p.status!=='draft'||!can('edit_process');
 ['saveDefinition','importSource'].forEach(id=>$(id).disabled=p.status!=='draft'||!can('edit_process'));
 $('publish').disabled=p.status!=='draft'||!can('publish_process');$('publish').hidden=!can('publish_process');$('fork').hidden=!can('edit_process');
 $('revisions').textContent=JSON.stringify(p.events,null,2);$('coverage').textContent=JSON.stringify(cov,null,2);
 $('run').disabled=p.status!=='published'||!can('edit_case');renderGraph();
}
function activeDefinition(){return S.run?.document.definition||S.process?.definition;}
function renderGraph(){
 const d=activeDefinition();if(!d)return;
 const main=['start','c_anwendungsbereich','c_persoenlich','c_gegenstand','c_neue_anteile','l_wertwahl','c_antrag','c_kst_sicher','c_passivueberhang','c_besteuerungsrecht','l_asset_taxright','c_sonstige_gegenleistung','c_grenze_gegenleistung','c_rueckwirkung','l_selected','r_buchwert'];
 const pos={};main.forEach((id,i)=>pos[id]=[260,30+i*117]);
 Object.assign(pos,{c_aufstockung:[570,960],l_mindestwert:[570,1410],r_nicht20:[860,180],r_gemeiner_wert:[860,670],r_stichtag:[860,1570],l_unknown:[10,1500],l_conflicted:[10,1690],l_manual:[860,1850]});
 const path=new Set(S.run?.document.path||[]);const taken=new Set((S.run?.document.events||[]).filter(e=>e.kind==='EDGE_SELECTED').map(e=>e.detail.edge_id));
 const only=$('pathOnly').checked&&S.run;const ns='http://www.w3.org/2000/svg';
 $('graph').innerHTML='<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#839eab"/></marker></defs>';
 for(const e of d.edges){if(only&&!taken.has(e.id))continue;const a=pos[e.source],b=pos[e.target];if(!a||!b)continue;const p=document.createElementNS(ns,'path');p.setAttribute('d',`M${a[0]+100},${a[1]+65} C${a[0]+100},${a[1]+95} ${b[0]+100},${b[1]-25} ${b[0]+100},${b[1]}`);p.setAttribute('class','edge'+(taken.has(e.id)?' taken':''));p.setAttribute('marker-end','url(#arrow)');$('graph').append(p);}
 for(const n of d.nodes){if(only&&!path.has(n.id))continue;const xy=pos[n.id];const g=document.createElementNS(ns,'g');g.setAttribute('class','node'+(path.has(n.id)?' visited':'')+(n.id.startsWith('l_')?' local':'')+(n.id===S.node?' selected':''));g.setAttribute('transform',`translate(${xy[0]},${xy[1]})`);g.setAttribute('tabindex','0');g.setAttribute('role','button');g.setAttribute('aria-label',n.title);g.innerHTML=`<rect width="215" height="66" rx="7"/><text x="10" y="21">${h(n.id)}</text><text x="10" y="43">${h(n.title.slice(0,30))}</text><text x="10" y="57" style="font-size:9px">${n.source_node_id?'Quellknoten':'Lokale Normalisierung'}</text>`;g.onclick=()=>inspect(n.id);g.onkeydown=e=>{if(e.key==='Enter')inspect(n.id);};$('graph').append(g);}
 $('edges').innerHTML='<table><thead><tr><th>Kante</th><th>Von</th><th>Nach</th><th>Bedingung</th><th>Ausgef\u00fchrt</th></tr></thead><tbody>'+d.edges.map(e=>`<tr><td>${h(e.id)}</td><td>${h(e.source)}</td><td>${h(e.target)}</td><td>${outcome[e.outcome]||h(e.outcome)}</td><td>${taken.has(e.id)?'Ja':'\u2014'}</td></tr>`).join('')+'</tbody></table>';
 inspect(S.node,false);
}
function inspect(id,redraw=true){
 S.node=id;const d=activeDefinition();const n=d?.nodes.find(x=>x.id===id);if(!n)return;
 const ev=S.run?.document.events.find(e=>e.kind==='CHECK_EVALUATED'&&e.detail.node_id===id);
 $('inspector').innerHTML=`<h3>${h(n.title)}</h3><p><b>${h(n.id)}</b> \u00b7 ${h(n.kind)} \u00b7 Quelle: ${h(n.source_node_id||'lokale Regelerg\u00e4nzung')}</p><p>Gebundene Regeln: ${h(n.rules.join(', ')||'Ergebnis / Start')}</p><pre>${h(ev?JSON.stringify(ev.detail,null,2):JSON.stringify(d.edges.filter(e=>e.source===id),null,2))}</pre>`;
 if(redraw)renderGraph();
}
function fields(){return S.schema.core_fields.map(f=>({...f,group:'Fallakte / '+f.section,type:f.type==='boolean'?'bool':f.type==='number'?'money':f.type,core:true})).concat(S.schema.extra_fields);}
function renderFacts(values){
 const fs=fields();const valuesByKey=values||{...Object.fromEntries((S.case?.facts||[]).map(f=>[f.key,f])),...(S.inputs?.extra_facts||{})};
 const groups=[...new Set(fs.map(f=>f.group))];
 $('facts').innerHTML=groups.map((group,i)=>`<details class="group" ${i===0?'open':''}><summary>${h(group)}</summary>${fs.filter(f=>f.group===group).map(f=>{
 const r=valuesByKey[f.key]||{value:null,verification:'unknown',evidence_ref:''};let control='';
 if(f.type==='bool'||f.type==='choice'){let opts=f.type==='bool'?[{value:true,label:'Ja'},{value:false,label:'Nein'}]:(f.choices||[]).map(v=>typeof v==='object'?v:{value:v,label:v});control=`<select data-part="value"><option value="">Noch unbekannt</option>${opts.map(v=>`<option value="${h(v.value)}" ${v.value===r.value?'selected':''}>${h(v.label)}</option>`).join('')}</select>`;}
 else if(f.type==='schedule')control=`<textarea data-part="value" rows="5" placeholder='[{"id":"Maschine","book":300000,"fair":1500000,"kind":"linear","original_cost":600000,"annual_rate":0.1}]'>${h(r.value==null?'':JSON.stringify(r.value,null,2))}</textarea>`;
 else control=`<input data-part="value" type="${f.type==='date'?'date':f.type==='money'||f.type==='fraction'?'number':'text'}" step="any" value="${h(r.value??'')}">`;
 return `<div class="fact" data-key="${h(f.key)}"><label>${h(f.label)}</label><div class="factRow">${control}<select data-part="verification">${[['unknown','Unbekannt'],['reported','Ungepr\u00fcft'],['confirmed','Best\u00e4tigt']].map(([v,l])=>`<option value="${v}" ${r.verification===v?'selected':''}>${l}</option>`).join('')}</select></div><input data-part="ref" aria-label="Nachweisreferenz ${h(f.label)}" placeholder="Nachweis oder Aktenvermerk" value="${h(r.evidence_ref||'')}">${r.observations?.length?'<p class="small">Zus\u00e4tzliche Beobachtungen bleiben erhalten. Fachliche Konfliktkl\u00e4rung erforderlich.</p>':''}</div>`;
 }).join('')}</details>`).join('');
 $('facts').querySelectorAll('input,select,textarea').forEach(el=>{el.disabled=!can('edit_case');el.oninput=()=>{S.dirty=true;renderFreshness();};});
 ['sampleNormal','sampleNegative','saveInputs','run'].forEach(id=>$(id).hidden=!can('edit_case'));
}
async function selectCase(id){
 if(S.dirty&&!confirm('Nicht gespeicherte Eingaben verwerfen?')){$('caseSelect').value=S.case.id;return;}
 S.case=await api('/api/cases/'+id);S.inputs=await api('/api/functional/cases/'+id+'/inputs');S.dirty=false;renderFacts();await history();renderFreshness();
}
function readFacts(){
 const output={},meta=Object.fromEntries(fields().map(f=>[f.key,f]));
 $('facts').querySelectorAll('[data-key]').forEach(row=>{const key=row.dataset.key, f=meta[key];let value=row.querySelector('[data-part=value]').value;
 if(value==='')value=null;else if(f.type==='bool')value=value==='true';else if(f.type==='money'||f.type==='fraction')value=Number(value);else if(f.type==='schedule')value=JSON.parse(value);
 const existing=S.inputs?.extra_facts[key]||S.case?.facts.find(x=>x.key===key)||{};
 output[key]={value,verification:value==null?'unknown':row.querySelector('[data-part=verification]').value,evidence_ref:row.querySelector('[data-part=ref]').value,...(existing.observations?.length?{observations:existing.observations}:{})};
 });return output;
}
async function saveFacts(){
 const all=readFacts(),coreKeys=new Set(S.schema.core_fields.map(f=>f.key));
 const core=[...S.case.facts.filter(f=>!coreKeys.has(f.key)),...S.schema.core_fields.map(f=>({key:f.key,...all[f.key]}))];
 S.case=await api('/api/cases/'+S.case.id+'/facts',{method:'PUT',body:JSON.stringify({facts:core})});
 const extra=Object.fromEntries(Object.entries(all).filter(([k])=>!coreKeys.has(k)));
 S.inputs=await api('/api/functional/cases/'+S.case.id+'/inputs',{method:'PUT',body:JSON.stringify({extra_facts:extra,expected_hash:S.inputs.inputs_hash})});
 S.dirty=false;renderFreshness();toast('Fallangaben und Nachweise gespeichert.');
}
async function history(){
 if(!S.case)return;const rows=(await api('/api/functional/cases/'+S.case.id+'/runs')).runs;
 $('runList').innerHTML=rows.length?rows.map(r=>`<button class="processItem" data-run="${h(r.id)}"><strong>${h(states[r.overall]||r.overall)}</strong><small>${h(r.created_at)} \u00b7 ${h(r.actor)} \u00b7 ${h(r.package_id)}</small></button>`).join(''):'<p>Noch keine integrierten Pr\u00fcfl\u00e4ufe.</p>';
 $('runList').querySelectorAll('button').forEach(b=>b.onclick=safe(async()=>{S.run=await api('/api/functional/runs/'+b.dataset.run);renderResult();tab('overview');}));
}
function renderFreshness(){
 if(!S.run)return;const match=S.run.current_inputs_match&&!S.dirty&&S.case?.id===S.run.case_id;
 $('freshness').textContent=!match?'Historischer Lauf: aktuelle Eingaben weichen ab. Erst speichern und erneut pr\u00fcfen.':S.run.verification.valid?'Integrit\u00e4t und deterministische Wiederholung best\u00e4tigt. Prozess und Quellenstand sind eingefroren.':'Integrit\u00e4t oder Wiederholung nicht best\u00e4tigt.';
 $('approve').disabled=!match||!S.run.verification.valid||S.run.overall!=='READY_FOR_EXPERT_REVIEW';$('reject').disabled=!match||!S.run.verification.valid;
}
function renderResult(){
 const r=S.run,d=r.document,p=d.report;$('result').hidden=false;$('runStatus').textContent=states[r.overall]||r.overall;
 $('consequences').innerHTML=`<p><b>Prozessversion:</b> ${h(r.package_id)} \u00b7 <b>Regeln:</b> ${h(p.engine_version)}</p><p><b>Gew\u00e4hlter / effektiver Wertansatz:</b> ${h(p.selected.mode)} / ${h(p.selected.effective_mode)}. Zahlen sind vorl\u00e4ufige Rechenergebnisse, keine Steuerfestsetzung.</p><div class="resultgrid"><div><h3>\u00dcbernehmende GmbH</h3><p>Steuerlicher Nettowert: <b>${money(p.consequences[0].tax_basis)}</b></p></div><div><h3>Einbringender</h3><p>Vorl\u00e4ufiger Gewinn: <b>${money(p.consequences[1].gross_gain_preliminary)}</b></p><p>Anschaffungskosten der Anteile: ${money(p.consequences[1].new_share_cost_basis_preliminary)}</p></div><div><h3>Mindestwert / Aufstockung</h3><p>Nettoansatz: ${money(p.minimum_valuation.minimum_net_value)}</p><p>Aufstockung: ${money(p.minimum_valuation.minimum_uplift)}</p></div></div><p class="small">${h(p.minimum_valuation.note)}</p><p class="small">${h(p.warnings.join(' '))}</p>`;
 $('path').innerHTML=d.path.map(id=>`<button data-node="${h(id)}">${h(id)}</button>`).join('');$('path').querySelectorAll('button').forEach(b=>b.onclick=()=>{tab('overview');inspect(b.dataset.node);$('inspector').scrollIntoView({block:'center',behavior:'smooth'});});
 $('assessments').innerHTML='<table><tr><th>Pr\u00fcfung</th><th>Status</th><th>Begr\u00fcndung / Fakten</th></tr>'+p.assessments.map(a=>`<tr><td>${h(a.code)}<br>${h(a.label)}</td><td>${h(a.status)}</td><td>${h(a.reason)}<br><small>${h(a.fact_keys.join(', '))}</small></td></tr>`).join('')+'</table>';
 $('auditEvents').innerHTML=d.events.map(e=>`<details><summary>#${e.seq} ${h(e.kind)} ${h(e.detail.node_id||e.detail.edge_id||'')}</summary><pre>${h(JSON.stringify(e,null,2))}</pre></details>`).join('');
 $('details').textContent=JSON.stringify({effective_date:p.effective_date,assets:p.asset_allocation,consequences:p.consequences,sperrfrist:p.sperrfrist,proof_obligations:p.proof_obligations,manual_topics:p.manual_topics,handoff:d.handoff},null,2);
 $('approvals').innerHTML=r.reviews.map(x=>`<p><b>${h(x.decision)}</b> \u00b7 ${h(x.reviewer)} \u00b7 ${h(x.at)}<br>${h(x.note)}</p>`).join('')||'<p class="small">Noch keine menschliche Freigabe.</p>';
 $('approve').hidden=!can('approve_case');$('reject').hidden=!can('approve_case');renderFreshness();renderGraph();
}
function fillSample(negative){
 const vals={asset_type:'betrieb',receiving_company:true,new_shares:true,essential_assets:true,future_corporate_tax:true,assets_ge_liabilities:!negative,german_tax_right:true,book_value:negative?-200000:100000,fair_value:negative?1000000:400000,other_consideration:0,application_timely:true,planned_disposal:false,transaction_type:'ausgliederung',registered_merchant:true,liabilities_not_exceed_assets:true,registration_effective:true,register_entry_date:'2026-02-01',recipient_eu_eea:true,recipient_formed_eu_eea:true,individual_business:true,contributor_eu_eea:true,german_tax_right_received_shares:true,retroactive_requested:true,tax_transfer_date:'2025-12-31',register_filing_date:'2026-01-01',profit_method:'bilanz',valuation_choice:'buchwert',transfer_costs:0,withdrawals:0,contributions:0,event_type:'keines',contains_real_estate:false};
 if(negative){vals.tax_liabilities=500000;vals.asset_schedule=[{id:'Maschine',book:300000,fair:1500000,kind:'linear',original_cost:600000,annual_rate:.1}];}
 renderFacts(Object.fromEntries(Object.entries(vals).map(([k,v])=>[k,{value:v,verification:'confirmed',evidence_ref:'SYNTHETISCH: Musterfall '+(negative?'Passivueberhang':'Buchwert')}])));S.dirty=true;renderFreshness();toast('Synthetische Werte eingef\u00fcgt; noch nicht gespeichert.');
}
async function boot(){
 S.schema=await api('/api/functional/schema');const u=S.schema.identity;
 $('identity').textContent=`${u.org_id} / ${{viewer:'Leser',editor:'Autor',reviewer:'Reviewer'}[u.role]}`;
 $('newProcess').hidden=!can('create_process');$('editorTab').hidden=!can('edit_process');
 S.cases=(await api('/api/cases')).cases;$('caseSelect').innerHTML=S.cases.map(c=>`<option value="${h(c.id)}">${h(c.title)}</option>`).join('');
 await processes();const first=S.cases.find(c=>c.title.includes('Musterfall A'))||S.cases[0];if(first){$('caseSelect').value=first.id;await selectCase(first.id);}
}
$('caseSelect').onchange=safe(e=>selectCase(e.target.value));$('pathOnly').onchange=renderGraph;
$('sampleNormal').onclick=()=>fillSample(false);$('sampleNegative').onclick=()=>fillSample(true);$('saveInputs').onclick=safe(saveFacts);
$('caseForm').onsubmit=safe(async e=>{e.preventDefault();if(S.dirty){toast('Eingaben zuerst speichern.');return;}if(!S.case||!S.process)return;$('run').disabled=true;try{S.run=await api('/api/functional/cases/'+S.case.id+'/runs',{method:'POST',body:JSON.stringify({process_id:S.process.id,expected_case_hash:S.inputs.case_hash,expected_inputs_hash:S.inputs.inputs_hash,as_of:S.schema.law_as_of})});renderResult();await history();tab('overview');toast('Pr\u00fcflauf abgeschlossen: '+(states[S.run.overall]||S.run.overall));}finally{$('run').disabled=S.process.status!=='published';}});
$('newProcess').onclick=safe(async()=>{const label=prompt('Name des neuen Prozesses:');if(!label)return;const p=await api('/api/functional/processes',{method:'POST',body:JSON.stringify({label})});await processes(p.id);tab('editor');});
$('fork').onclick=safe(async()=>{const p=await api('/api/functional/processes/'+S.process.id+'/draft',{method:'POST'});await processes(p.id);tab('editor');});
$('saveDefinition').onclick=safe(async()=>{const p=await api('/api/functional/processes/'+S.process.id,{method:'PUT',body:JSON.stringify({definition:JSON.parse($('definition').value),expected_hash:S.process.definition_hash,reason:$('changeReason').value})});await processes(p.id);toast('Entwurf mit Version und \u00c4nderungsgrund gespeichert.');});
$('publish').onclick=safe(async()=>{if($('definition').value!==JSON.stringify(S.process.definition,null,2)){toast('Prozess\u00e4nderungen zuerst speichern.');return;}if(!confirm('Normalisierte Kanten, Regeln und Quellenbegrenzung gepr\u00fcft? Diese Best\u00e4tigung ist keine automatische Steuerfreigabe.'))return;const note=prompt('Pr\u00fcfvermerk (mindestens 12 Zeichen):');if(!note)return;const p=await api('/api/functional/processes/'+S.process.id+'/publish',{method:'POST',body:JSON.stringify({expected_hash:S.process.definition_hash,confirm_normalizations:true,acknowledge_source_limits:true,note})});await processes(p.id);toast('Referenztests bestanden; neue Version ver\u00f6ffentlicht.');});
$('importSource').onclick=safe(async()=>{const p=await api('/api/functional/processes/'+S.process.id+'/source',{method:'POST',body:JSON.stringify({source:JSON.parse($('sourceJson').value),expected_hash:S.process.definition_hash,reason:$('changeReason').value})});await processes(p.id);toast('Quell-Snapshot eingefroren; fachliche Normalisierungen bleiben explizit.');});
$('export').onclick=()=>{if(S.run)location.href='/api/functional/runs/'+S.run.id+'/export';};
async function review(decision){const note=prompt('Fachlicher Pr\u00fcfvermerk (mindestens 12 Zeichen):');if(!note)return;S.run=await api('/api/functional/runs/'+S.run.id+'/review',{method:'POST',body:JSON.stringify({decision,note,expected_run_hash:S.run.document_hash})});renderResult();}
$('approve').onclick=safe(()=>review('approved'));$('reject').onclick=safe(()=>review('rejected'));
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
window.addEventListener('beforeunload',e=>{if(S.dirty){e.preventDefault();e.returnValue='';}});
safe(boot)();
})();
