"use strict";

// No remote browser dependencies. All execution state and decisions come from the backend.
const $ = (id) => document.getElementById(id);
const h = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
const deMoney = (n) => n == null ? "—" : new Intl.NumberFormat("de-DE", {style:"currency",currency:"EUR",maximumFractionDigits:2}).format(n);
const deTimestamp = (v) => v ? new Date(v).toLocaleString("de-DE", {day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",fractionalSecondDigits:3}) : "Nicht erfasst";
const deDate = (v) => v ? new Date(v).toLocaleString("de-DE", {dateStyle:"short",timeStyle:"short"}) : "—";
const ellipsis = (s, n=22) => String(s||"").length > n ? String(s).slice(0,n)+"…" : String(s||"");
const state = {config:null,cases:[],case:null,versions:[],graph:null,graphVersion:"umwstg20-v1",runs:[],run:null,
               node:"SCOPE",edge:null,eventSeq:null,provenance:null,provenanceCache:{},tab:"workspace",dirty:false,pathOnly:false,editorVersion:null,editorGraph:null};
const nodeKindDE = {ACTION:"Aktion",DECISION:"Prüfung",HUMAN_GATE:"Fachliche Freigabe",TERMINAL:"Ergebnis"};
const outcomeDE = {yes:"Ja",no:"Nein",unknown:"Unbekannt",pending:"Ausstehend",approved:"Freigegeben",rejected:"Abgelehnt",always:"Weiter"};
const auditTypeDE = {RUN_STARTED:"Prüflauf gestartet",NODE_ENTERED:"Knoten betreten",SIGNAL_EVALUATED:"Prüfkriterium ausgewertet",GUARDS_EVALUATED:"Kantenbedingungen geprüft",EDGE_SELECTED:"Kante gewählt",CALCULATION:"Berechnung",RECOMMENDATION:"Empfehlung erstellt",RUN_FINISHED:"Prüflauf abgeschlossen"};

async function api(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"},credentials:"same-origin",...options});
  const text = await response.text();
  let data; try { data = JSON.parse(text); } catch { data = {detail:text.slice(0,200)}; }
  if(!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail||data));
  return data;
}
function toast(message, isError=false) {
  const el=$('toast'); el.textContent=message;el.hidden=false;el.classList.toggle('error',isError);
  clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.hidden=true,5400);
}
function busy(button, value) { if(!button)return;button.disabled=value;button.dataset.original||=button.innerHTML;button.innerHTML=value?'Bitte warten …':button.dataset.original; }
function copy(obj){return JSON.parse(JSON.stringify(obj));}
function statusStyle(status){return !status?"status-idle":status.includes("PRUEFPFAD_UNVOLLSTAENDIG")||status.includes("NICHT")||status.includes("ABGELEHNT")?"status-block":status.includes("FEHLEN")||status.includes("OFFEN")?"status-warn":"status-ok";}
function statusShort(status){return ({"FREIGABE_OFFEN":"Freigabe offen","FREIGEGEBEN_IM_PROTOTYP":"Freigegeben","ANWENDUNGSBEREICH_OFFEN":"§20 prüfen","NACHWEISE_FEHLEN":"Belege fehlen","BUCHWERT_NICHT_GESICHERT":"Buchwert fraglich","FREIGABE_ABGELEHNT":"Abgelehnt","PRUEFPFAD_UNVOLLSTAENDIG":"Prüfpfad unvollständig"})[status]||status||"Noch offen";}
function factSignature(facts){return JSON.stringify([...facts].sort((a,b)=>a.key.localeCompare(b.key)).map(f=>[f.key,f.value,f.verification,f.evidence_ref,f.observations||[]]));}
function runIsStale(){return !!state.run && (state.dirty || state.run.graph_version!==state.graphVersion || factSignature(state.case.facts)!==factSignature(Object.values(state.run.facts_snapshot)));}
function updateRunNotice(){
  const stale=runIsStale(), invalid=state.run && !state.run.verification?.valid;
  const notice=$('resultFreshness');notice.hidden=!stale&&!invalid;
  notice.textContent=stale?'Historischer Prüflauf: Die Eingaben weichen vom eingefrorenen Sachverhalt ab. Vor einer Freigabe speichern und erneut prüfen. Bericht und Prüfpfad zeigen weiterhin den damaligen Stand.':invalid?'Dieser Prüflauf ist nicht vollständig nach dem aktuellen Audit-Schema belegt. Integritätsprüfung im Bericht beachten und einen neuen Prüflauf ausführen.':'';
  $('recommendationPanel').querySelectorAll('[data-review]').forEach(button=>button.disabled=stale||invalid);
}
function reviewHTML(run){
  const review=run?.events.find(e=>e.event_type==='SIGNAL_EVALUATED'&&e.detail.signal==='professional_review')?.detail.review_record;
  return review?`<h4>Dokumentierte Fachentscheidung</h4><p><strong>${h(outcomeDE[review.decision])}</strong> · ${h(review.reviewer)} · ${h(deDate(review.created_at))}</p><p>${h(review.note)}</p>`:'';
}

async function boot(){
  try {
    const [conf, graphList, caseList] = await Promise.all([api('/api/config'), api('/api/graphs'),api('/api/cases')]);
    state.config=conf;$('appVersion').textContent=conf.version;
    applyPermissions();state.versions=graphList.graphs;state.cases=caseList.cases;
    $('healthBadge').textContent='System bereit';$('healthBadge').classList.add('ready');
    state.graphVersion=state.versions.find(v=>v.status==='published')?.id || 'umwstg20-v1';
    state.editorVersion=state.graphVersion;
    renderVersionsSelect();
    const first=state.cases.find(x=>x.title.includes('Musterfall A')) || state.cases[0];
    if (first) await selectCase(first.id);else toast('Keine Fallakten vorhanden.',true);
    renderEditorVersionList();
    await loadEditor(state.editorVersion);
  } catch(e) { $('healthBadge').textContent='Systemfehler';toast('Initialisierung: '+e.message,true); }
}
function can(cap){return !!state.config?.capabilities?.[cap];}
function applyPermissions(){
  const identity=state.config.identity||{};
  const label=$('identityLabel');
  if(label)label.textContent=(identity.username||'Demo')+' · '+(identity.org_id||'demo')+' · '+(identity.role||'reviewer');
  for(const id of ['newCaseBtn'])$(id).hidden=!can('edit_case') || !can('create_process');
  for(const id of ['saveBtn','runBtn'])$(id).hidden=!can('edit_case');
  $('draftBtn').hidden=!can('edit_process');
  $('createProcessBtn').hidden=!can('create_process');
  $('saveGraphBtn').hidden=!can('edit_process');
  $('publishGraphBtn').hidden=!can('publish_process');
  document.querySelectorAll('[data-tab="model"]').forEach(b=>b.hidden=!(can('edit_process')||can('publish_process')));
}
async function refreshCaseList(){state.cases=(await api('/api/cases')).cases;renderCaseList();}
function renderCaseList(){
  $('caseCount').textContent=state.cases.length;
  $('caseList').innerHTML=state.cases.map((c,i)=>`<button class="case-item ${state.case?.id===c.id?'selected':''}" data-case="${h(c.id)}" title="${h(c.title)}"><span class="case-index">${String(i+1).padStart(2,'0')}</span><span class="case-copy"><strong>${h(c.title)}</strong><small>${c.latest_run ? h(statusShort(c.latest_run.status)) : 'Noch nicht geprüft'}</small></span></button>`).join('');
  $('caseList').querySelectorAll('[data-case]').forEach(e=>e.addEventListener('click',()=>selectCase(e.dataset.case)));
}
async function selectCase(caseId){
  if(state.dirty && !window.confirm('Nicht gespeicherte Änderungen verwerfen und Fall wechseln?'))return;
  const [theCase, list, theGraph] = await Promise.all([api(`/api/cases/${encodeURIComponent(caseId)}`),
    api(`/api/cases/${encodeURIComponent(caseId)}/runs`),api(`/api/graphs/${encodeURIComponent(state.graphVersion)}`)]);
  state.case=theCase;state.runs=list.runs;await setGraphContext(theGraph);state.run=null;state.dirty=false;
  if(list.runs.length){state.run=await api(`/api/runs/${encodeURIComponent(list.runs[0].id)}`);}
  if(state.run && state.run.graph_version!==state.graphVersion)state.run=null;
  state.node='SCOPE';state.edge=null;state.eventSeq=null;renderCaseList();renderCasesDetail();renderFacts();renderGraph();renderFindings();renderAudit();
}
function renderCasesDetail(){
  $('caseTitle').textContent=state.case?.title || '—';
  const run=state.run;
  $('lastRunBadge').textContent=run?`${statusShort(run.status)} · ${deDate(run.finished_at)}`:'Noch kein Prüflauf';
  $('lastRunBadge').className=run?`status-pill ${statusStyle(run.status)}`:'label-muted';
  $('saveBtn').textContent=state.dirty?'Ungespeichert · Speichern':'Änderungen speichern';
  updateRunNotice();
}
function renderVersionsSelect(){
 const published=state.versions.filter(g=>g.status==='published');
 $('graphVersionSelect').innerHTML=published.map(g=>`<option value="${h(g.id)}">v${h(g.version)} · ${h(g.id)}</option>`).join('');
 if(published.some(x=>x.id===state.graphVersion))$('graphVersionSelect').value=state.graphVersion;
}
function renderFacts(){
  if(!state.case || !state.config)return;
  const byKey=Object.fromEntries(state.case.facts.map(f=>[f.key,f]));
  const groups=[...new Set(state.config.fact_fields.map(f=>f.section))];
  $('factsForm').innerHTML=groups.map((section)=>`<div class="fact-group"><div class="fact-group-title">${h(section)}</div>${state.config.fact_fields.filter(f=>f.section===section).map((meta)=>{
    const fact=byKey[meta.key]||{value:null,verification:'unknown',evidence_ref:''};
    let options;
    if(meta.type==='boolean') options=`<option value="">Noch unbekannt</option><option value="true" ${fact.value===true?'selected':''}>Ja</option><option value="false" ${fact.value===false?'selected':''}>Nein</option>`;
    else if(meta.type==='choice') options=`<option value="">Noch unbekannt</option>`+meta.choices.map(c=>`<option value="${h(c.value)}" ${fact.value===c.value?'selected':''}>${h(c.label)}</option>`).join('');
    const main=meta.type==='number' ? `<input class="fact-control" type="number" step="0.01" min="0" data-part="value" aria-label="${h(meta.label)}" value="${fact.value==null?'':h(fact.value)}" placeholder="Betrag eingeben"/>` : `<select class="fact-control" data-part="value" aria-label="${h(meta.label)}">${options}</select>`;
    const status=`<select class="fact-control verification" data-part="verification" aria-label="${h(meta.label)} – Nachweisstatus"><option value="unknown" ${fact.verification==='unknown'?'selected':''}>Unbekannt</option><option value="reported" ${fact.verification==='reported'?'selected':''}>Ungeprüft</option><option value="confirmed" ${fact.verification==='confirmed'?'selected':''}>Bestätigt</option></select>`;
    return `<div class="fact-field" data-key="${h(meta.key)}"><label class="fact-title">${h(meta.label)}</label><div class="fact-controls">${main}${status}</div><input data-part="evidence" aria-label="${h(meta.label)} – Nachweisreferenz" class="fact-control fact-evidence" value="${h(fact.evidence_ref)}" placeholder="Belegreferenz oder Aktenvermerk …"/><div class="fact-help">${h(meta.help)}</div>${fact.observations?.length?`<p class="help-text">${fact.observations.length} zusätzliche Beobachtung(en) gespeichert. Fachliche Klärung erforderlich; Ausführung gesperrt. Speichern erhält diese Nachweise.</p>`:''}</div>`;
  }).join('')}</div>`).join('');
  $('factsForm').querySelectorAll('input,select').forEach(el=>{el.disabled=!can('edit_case');el.addEventListener('input',()=>{state.dirty=true;renderCasesDetail();});});
}
function readFactInputs(){
  return [...$('factsForm').querySelectorAll('.fact-field')].map(row=>{
    const key=row.dataset.key, schema=state.config.fact_fields.find(f=>f.key===key);
    let value=row.querySelector('[data-part="value"]').value;
    if(value==='')value=null;
    else if(schema.type==='boolean')value=value==='true';
    else if(schema.type==='number')value=Number(value);
    const verification=value==null?'unknown':row.querySelector('[data-part="verification"]').value;
    const evidence_ref=value==null?'':row.querySelector('[data-part="evidence"]').value.trim();
    const observations=state.case.facts.find(f=>f.key===key)?.observations;
    return {key,value,verification,evidence_ref,...(observations?.length?{observations:copy(observations)}:{})};
  });
}
async function saveCase(silent=false){
  if(!state.case||!can('edit_case'))return;
  const payload={facts:readFactInputs(),actor:'Lokale Bearbeitung'};
  const result=await api(`/api/cases/${state.case.id}/facts`,{method:'PUT',body:JSON.stringify(payload)});
  state.case=result;state.dirty=false;renderCasesDetail();
  if(!silent)toast('Fallangaben und Nachweisreferenzen gespeichert.');
  return result;
}
async function runCase(){
  const btn=$('runBtn');busy(btn,true);
  try{
    await saveCase(true);
    const data=await api(`/api/cases/${state.case.id}/run`,{method:'POST',body:JSON.stringify({graph_version:state.graphVersion})});
    state.run=await api(`/api/runs/${data.run_id}`);state.eventSeq=null;
    state.runs=(await api(`/api/cases/${state.case.id}/runs`)).runs;
    await refreshCaseList();renderCasesDetail();renderGraph();renderFindings();renderAudit();
    toast('Prüflauf abgeschlossen: '+statusShort(data.result.status));
  }catch(e){toast('Ausführung fehlgeschlagen: '+e.message,true);}finally{busy(btn,false);}
}
function renderFindings(){
  const res=state.run?.result;
  $('resultStatus').textContent=res?statusShort(res.status):'Noch offen';
  $('resultStatus').className=`status-pill ${statusStyle(res?.status)}`;
  if(!res){$('recommendationPanel').innerHTML='<div class="empty-result"><div class="empty-result-icon">↗</div><strong>Noch kein Prüfergebnis</strong><p>Fallangaben prüfen und die Ausführung starten. Das Ergebnis basiert auf einem versionierten Prozessgraphen.</p></div>';}
  else {
    const missing=res.missing_evidence.length ? `<div class="result-section"><h4>FEHLENDE NACHWEISE</h4><ul>${res.missing_evidence.map(v=>`<li>${h(v)}</li>`).join('')}</ul></div>` : '';
    $('recommendationPanel').innerHTML=`<div class="result-hl"><h3>${h(res.title)}</h3><p>${h(res.assessment)}</p></div><div class="result-section"><h4>EMPFOHLENER NÄCHSTER SCHRITT</h4><div class="result-action">${h(res.recommended_action)}</div>${res.status==='FREIGABE_OFFEN' && can('approve_case')?'<div class="review-actions"><button data-review="approved" class="button button-secondary button-small">Freigabe dokumentieren</button><button data-review="rejected" class="button button-secondary button-small">Ablehnung dokumentieren</button></div>':''}</div>${missing}<div class="result-section"><h4>RECHNERISCHE WERTDIFFERENZ</h4><p>${res.valuation?.available?`${deMoney(res.valuation.fair_value)} − ${deMoney(res.valuation.book_value)} = <b>${deMoney(res.valuation.difference)}</b>`:'Noch nicht belegt.'}</p></div><div class="result-section"><h4>RISIKEN & HINWEISE</h4><ul>${res.warnings.map(v=>`<li>${h(v)}</li>`).join('')}</ul></div>`;
  }
  renderInspector();updateRunNotice();
}
function switchTab(name){
  state.tab=name;
  document.querySelectorAll('[data-tab]').forEach(b=>{const active=b.dataset.tab===name;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));});
  for(const n of ['workspace','audit','model']){$(n+'View').hidden=n!==name;$(n+'View').classList.toggle('view-active',n===name);}
  if(name==='audit')renderAudit();
  if(name==='model')renderEditorVersionList();
}
function renderAudit(){
  const sel=$('auditRunSelect');
  sel.innerHTML='<option value="">Prüflauf auswählen</option>'+state.runs.map(r=>`<option value="${h(r.id)}" ${state.run?.id===r.id?'selected':''}>${h(deDate(r.finished_at))} · ${h(statusShort(r.status))} · ${h(r.graph_version)}</option>`).join('');
  const run=state.run;
  $('printBtn').disabled=!run;$('exportAuditBtn').disabled=!run;
  if(!run){$('auditHeader').innerHTML='<p class="help-text">Noch kein Prüfpfad vorhanden. Erst einen Prüflauf starten.</p>';
    $('reportBody').innerHTML='<p class="help-text">Der fachliche Bericht wird nach dem Prüflauf erstellt.</p>';
    $('eventList').innerHTML='<div class="event-empty">Keine Ereignisse.</div>';$('printReport').innerHTML='';return;}
  const check=run.verification||{};
  $('auditHeader').innerHTML=`<div class="audit-stats"><div class="stat-cell"><div class="stat-num">${run.events.length}</div><div class="stat-caption">protokollierte Ereignisse</div></div><div class="stat-cell"><div class="stat-num">${run.result.path.length}</div><div class="stat-caption">durchlaufene Knoten</div></div><div class="stat-cell"><div class="stat-num">${run.result.selected_edges.length}</div><div class="stat-caption">gewählte Kanten</div></div></div><div class="audit-check"><span>Graphversion unverändert</span><strong>${check.graph_integrity?'✓ Bestätigt':'✕ Fehler'}</strong></div><div class="audit-check"><span>Ereignis-Hashkette</span><strong>${check.event_chain_integrity?'✓ Bestätigt':'✕ Fehler'}</strong></div><div class="audit-check"><span>Fall-Snapshot konsistent</span><strong>${check.facts_integrity?'✓ Bestätigt':'✕ Fehler'}</strong></div><div class="audit-check"><span>Empfehlung unverändert</span><strong>${check.result_integrity?'✓ Bestätigt':'✕ Fehler'}</strong></div><div class="inspector-edge-detail" style="margin-top:12px">Prüflauf: <code>${h(run.id)}</code><br>Stand: ${h(deDate(run.finished_at))}<br>Graph: ${h(run.graph_version)}</div>`;
  $('auditHeader').insertAdjacentHTML('beforeend', [['context_integrity','Quellen und Freigabenachweis'],['execution_integrity','Vollständigkeit und deterministische Wiederholung']].map(([key,label])=>`<div class="audit-check ${check[key]?'':'audit-failed'}"><span>${label}</span><strong>${check[key]?'✓ Bestätigt':'✕ Nicht bestätigt'}</strong></div>`).join(''));
  const res=run.result;
  $('reportBody').innerHTML=`<h3>${h(res.title)}</h3><p>${h(res.assessment)}</p><h4>Sachverhalt</h4><p>${h(res.case_description||'Synthetischer Prüffall.')}</p><h4>Prüfergebnis</h4><p><strong>${h(statusShort(res.status))}</strong></p><h4>Handlungsempfehlung</h4><p><strong>${h(res.recommended_action)}</strong></p><h4>Prüfungshinweise</h4><ul>${res.warnings.map(w=>`<li>${h(w)}</li>`).join('')}</ul>${res.missing_evidence.length?`<h4>Nachzufordern</h4><ul>${res.missing_evidence.map(e=>`<li>${h(e)}</li>`).join('')}</ul>`:''}<h4>Rechtsquellen</h4>${res.legal_sources.map(r=>`<a class="legal-link" href="${h(r.url)}" target="_blank" rel="noopener noreferrer">↗ ${h(r.label)}</a>`).join('')}`;
  $('reportBody').insertAdjacentHTML('beforeend',reviewHTML(run));
  renderEventList();
  $('printReport').innerHTML=`<h1>ProzessPilot · Prüfbericht</h1><p><strong>Fall:</strong> ${h(res.case_title)}<br><strong>Prüflauf:</strong> ${h(run.id)}<br><strong>Graphversion:</strong> ${h(run.graph_version)}<br><strong>Zeitpunkt:</strong> ${h(deDate(run.finished_at))}<br><strong>Ergebnis:</strong> ${h(statusShort(res.status))}</p><h2>Sachverhalt</h2><p>${h(res.case_description||'Synthetischer Prüffall.')}</p><h2>Prüfergebnis und rechtliche Würdigung</h2><p><strong>${h(res.title)}</strong></p><p>${h(res.assessment)}</p><h2>Handlungsempfehlung</h2><p>${h(res.recommended_action)}</p><h2>Rechnerische Wertdifferenz</h2><p>${res.valuation?.available?deMoney(res.valuation.difference):'Keine gesicherte Berechnung'}</p><h2>Offene Nachweise</h2><ul>${res.missing_evidence.map(w=>`<li>${h(w)}</li>`).join('')||'<li>Keine auf dem durchlaufenen Pfad erkannt.</li>'}</ul><h2>Risiken und Grenzen</h2><ul>${res.warnings.map(w=>`<li>${h(w)}</li>`).join('')}</ul><h2>Rechtsgrundlagen</h2><ul>${res.legal_sources.map(r=>`<li>${h(r.label)} · ${h(r.url)}</li>`).join('')}</ul><p class="print-note">Dieser Bericht ist keine Steuerberatung. Daten und Belege stammen aus einer synthetischen Demonstration. Der Prüfpfad kann als JSON gesondert exportiert werden.</p>`;
  $('printReport').insertAdjacentHTML('beforeend',reviewHTML(run));
}
function renderEventList(){
 const run=state.run;const query=$('eventFilter').value.toLowerCase().trim();
 if(!run){$('eventList').innerHTML='<div class="event-empty">Keine Ereignisse.</div>';return;}
 const matching=run.events.filter(e=>!query||`${e.event_type} ${JSON.stringify(e.detail)} ${e.seq}`.toLowerCase().includes(query));
 $('eventList').innerHTML=matching.length?matching.map(e=>{
   const detail=e.detail||{};
   const msg=detail.title||detail.reason||detail.edge_id||(detail.status?statusShort(detail.status):null)||outcomeDE[detail.expected]||auditTypeDE[e.event_type];
   const target=GraphAudit.eventTarget(e,run.events);
   const jump=target?.node||'';
   return `<div class="event-row ${state.eventSeq===e.seq?'event-selected':''}" data-seq="${e.seq}"><div class="event-no">#${e.seq}</div><div class="event-type">${h(auditTypeDE[e.event_type]||e.event_type.replaceAll('_',' '))}</div><div class="event-detail">${target?`<button class="text-button" data-event-target="${e.seq}">${h(msg)} · Im Graph prüfen ↗</button>`:h(msg)}<small class="event-meta">${h(detail.actor||'Graph-Executor')} · ${h(deTimestamp(e.at))}</small>${detail.candidates?`<details><summary>Alle Kantenbedingungen anzeigen</summary>${detail.candidates.map(c=>`<div><button class="text-button" data-audit-edge="${h(c.edge_id)}">${h(c.edge_id)} → ${h(c.target)}</button> · ${h(outcomeDE[c.outcome]||c.outcome)}: ${c.guard_result===true?'TRUE · erfüllt':c.guard_result===false?'FALSE · nicht erfüllt':'UNKNOWN · nicht aufgezeichnet'}</div>`).join('')}</details>`:''}</div><div class="event-hash" title="${h(e.event_hash)}">${h(e.event_hash.slice(0,17))}…</div></div>`;
 }).join(''):'<div class="event-empty">Keine Treffer.</div>';
 $('eventList').querySelectorAll('[data-event-target]').forEach(button=>button.addEventListener('click',()=>selectExecutionEvent(run.events.find(e=>e.seq===Number(button.dataset.eventTarget)))));
 $('eventList').querySelectorAll('[data-audit-edge]').forEach(button=>button.addEventListener('click',()=>{selectAuditEdge(button.dataset.auditEdge);switchTab('workspace');focusGraphNode(state.node);}));
}
function renderEditorVersionList(){
 $('versionsList').innerHTML=state.versions.map(g=>`<div class="version-row"><div><strong>v${g.version} · ${h(g.label)}</strong><small>${g.status==='published'?'Veröffentlicht':'Entwurf'} · ${h(g.id)}</small></div><button data-version="${h(g.id)}">Öffnen</button></div>`).join('');
 $('versionsList').querySelectorAll('[data-version]').forEach(btn=>btn.addEventListener('click',()=>loadEditor(btn.dataset.version).catch(e=>toast(e.message,true))));
}
async function loadEditor(id){
  const graph=await api(`/api/graphs/${id}`);state.editorVersion=id;state.editorGraph=graph;
  $('graphEditor').value=JSON.stringify({label:graph.label,nodes:graph.nodes,edges:graph.edges},null,2);
  const draft=graph.meta.status==='draft';$('graphEditor').readOnly=!draft||!can('edit_process');
  $('editorStatus').textContent=draft?'Entwurf – bearbeitbar':'Veröffentlicht – gesperrt';
  $('saveGraphBtn').disabled=!draft||!can('edit_process');$('publishGraphBtn').disabled=!draft||!can('publish_process');
  $('graphValidation').textContent=`Version ${graph.meta.version} · ${graph.nodes.length} Knoten · ${graph.edges.length} Kanten\nChecksumme: ${graph.meta.checksum||'Entwurf (noch ohne Veröffentlichungs-Hash)'}`;
  $('graphValidation').className='validation-box';
  try {
    const history=await api(`/api/graphs/${id}/revisions`);
    $('revisionHistory').innerHTML=history.revisions.length ? history.revisions.map(r=>`<div class="revision-item"><strong>Revision ${r.revision} · ${h(r.actor)}</strong><span>${h(deDate(r.created_at))}</span><p>${h(r.reason)}</p><small>${r.diff.initial?'Initialfassung':`Knoten: +${r.diff.nodes?.added?.length||0} / −${r.diff.nodes?.deleted?.length||0} / geändert ${r.diff.nodes?.changed?.length||0} · Kanten: +${r.diff.edges?.added?.length||0} / −${r.diff.edges?.deleted?.length||0} / geändert ${r.diff.edges?.changed?.length||0}`}</small></div>`).join('') : '<p class="help-text">Für ältere Graphversionen ist noch keine Revisionshistorie vorhanden.</p>';
  } catch(e) { $('revisionHistory').textContent='Änderungshistorie nicht verfügbar: '+e.message; }
}
function parseGraphEditor(){const val=JSON.parse($('graphEditor').value);if(!val.label||!Array.isArray(val.nodes)||!Array.isArray(val.edges))throw new Error('Graph muss label, nodes und edges enthalten.');return val;}
async function graphValidate(){
 try{const res=await api('/api/graphs/validate',{method:'POST',body:JSON.stringify(parseGraphEditor())});
   $('graphValidation').className='validation-box '+(res.valid?'ok':'error');
   $('graphValidation').textContent=res.valid?`✓ Struktur gültig · ${res.node_count} Knoten und ${res.edge_count} Kanten. Fachrechtliche Prüfung steht weiterhin aus.`:'Strukturelle Fehler:\n'+res.errors.join('\n');
 }catch(e){$('graphValidation').className='validation-box error';$('graphValidation').textContent=e.message;}
}
async function newDraft(){
 try{const src=state.editorVersion||state.graphVersion;const name=window.prompt('Bearbeitungskürzel oder Name:', 'Hackathon-Team');if(!name)return;
   const obj=await api(`/api/graphs/${src}/draft`,{method:'POST',body:JSON.stringify({actor:name})});
   state.versions=(await api('/api/graphs')).graphs;renderEditorVersionList();await loadEditor(obj.meta.id);toast('Editierbarer Graph-Entwurf angelegt.');
 }catch(e){toast(e.message,true);}
}
async function saveGraph(){
 if(state.editorGraph?.meta.status!=='draft')return;
 try{const name=window.prompt('Bearbeitungskürzel oder Name:', 'Hackathon-Team');if(!name)return;
   const reason=window.prompt('Änderungsgrund für den Prüfpfad:', 'Anpassung der Prozessschritte im Hackathon');if(!reason)return;
   const data=await api(`/api/graphs/${state.editorVersion}`,{method:'PUT',body:JSON.stringify({actor:name,reason,graph:parseGraphEditor()})});
   state.versions=(await api('/api/graphs')).graphs;renderEditorVersionList();await loadEditor(data.meta.id);toast('Entwurf versioniert und gespeichert.');
 }catch(e){toast(e.message,true);}
}
async function publishGraph(){
 if(state.editorGraph?.meta.status!=='draft')return;
 if(!window.confirm('Diese Version strukturell validieren und unveränderlich veröffentlichen? Die fachrechtliche Richtigkeit bleibt gesondert zu bestätigen.'))return;
 const reviewer=window.prompt('Name der prüfenden Person (Dokumentation):');if(!reviewer)return;
 try{
   // Save first to ensure published graph equals the visible editor state.
   await api(`/api/graphs/${state.editorVersion}`,{method:'PUT',body:JSON.stringify({actor:reviewer,reason:'Version zur fachlichen Strukturprüfung eingereicht',graph:parseGraphEditor()})});
   const obj=await api(`/api/graphs/${state.editorVersion}/publish`,{method:'POST',body:JSON.stringify({actor:reviewer,confirm_expert_review:true})});
   state.versions=(await api('/api/graphs')).graphs;state.graphVersion=obj.meta.id;renderVersionsSelect();
   await setGraphContext(obj);state.edge=null;state.node='SCOPE';if(state.run?.graph_version!==state.graphVersion)state.run=null;renderCasesDetail();renderGraph();renderFindings();renderAudit();renderEditorVersionList();await loadEditor(obj.meta.id);
   toast('Graph veröffentlicht. Neue Prüfläufe können diese Version verwenden.');
 }catch(e){toast(e.message,true);}
}
function exportGraph(){
 if(!state.editorVersion){toast('Zuerst Graphversion auswählen.',true);return;}
 window.location.href=`/api/graphs/${encodeURIComponent(state.editorVersion)}/export`;
}
function downloadAudit(){if(!state.run){toast('Erst einen Prüflauf starten.',true);return;}window.location.href=`/api/runs/${state.run.id}/audit`;}
async function newCase(e){e.preventDefault();
 const form=$('newCaseForm'), title=$('newCaseTitle').value.trim(),description=$('newCaseDescription').value;
 try{const obj=await api('/api/cases',{method:'POST',body:JSON.stringify({title,description})});
   $('newCaseDialog').close();form.reset();await refreshCaseList();await selectCase(obj.id);toast('Neue synthetische Fallakte angelegt.');
 }catch(err){toast(err.message,true);}
}
async function handleReview(decision='approved'){
 if(!state.run||state.run.status!=='FREIGABE_OFFEN'){toast('Zuerst vollständig prüfen, danach Freigabe dokumentieren.',true);return;}
 if(runIsStale()||!state.run.verification?.valid){toast('Vor der Freigabe einen vollständigen Prüflauf mit den aktuellen Angaben ausführen.',true);return;}
 if(!window.confirm(decision==='approved'?'Wurde der Prüflauf fachlich geprüft? Die Freigabe ist nur für befugte Fachpersonen vorgesehen.':'Fachliche Ablehnung dieses Prüflaufs dokumentieren?'))return;
 const reviewer=window.prompt('Name der fachlich prüfenden Person:');if(!reviewer)return;
 const note=window.prompt('Fachliche Begründung / Prüfvermerk (min. 12 Zeichen):');if(!note)return;
 try{
   await api(`/api/cases/${state.case.id}/review`,{method:'POST',body:JSON.stringify({run_id:state.run.id,reviewer,decision,note})});
   await runCase();toast('Fachentscheidung dokumentiert und neuer Prüflauf ausgeführt.');
 }catch(e){toast(e.message,true);}
}

function wire(){
 wireGraphNavigation();
 $('saveBtn').addEventListener('click',async()=>{try{await saveCase();}catch(e){toast(e.message,true);}});
 $('runBtn').addEventListener('click',runCase);
 $('pathToggle').addEventListener('click',()=>{state.pathOnly=!state.pathOnly;renderGraph();});
 $('graphVersionSelect').addEventListener('change',async(e)=>{
   state.graphVersion=e.target.value;
   await setGraphContext(await api(`/api/graphs/${state.graphVersion}`));
   if(state.run?.graph_version!==state.graphVersion)state.run=null;
   state.node='SCOPE';state.edge=null;state.eventSeq=null;renderCasesDetail();renderGraph();renderFindings();renderAudit();
   toast('Graphversion geändert; bestehende Prüfläufe behalten ihre alte Version.');
 });
 document.querySelectorAll('[data-tab]').forEach(btn=>btn.addEventListener('click',()=>switchTab(btn.dataset.tab)));
 $('eventFilter').addEventListener('input',renderEventList);
 $('auditRunSelect').addEventListener('change',async(e)=>{
   if(!e.target.value)return;
   try{const old=await api(`/api/runs/${e.target.value}`);
     if(state.dirty&&!window.confirm('Nicht gespeicherte Eingaben verwerfen, um den historischen Prüflauf zu öffnen?'))return;
     state.dirty=false;renderFacts();
     state.run=old;state.graphVersion=old.graph_version;
     await setGraphContext(await api(`/api/graphs/${old.graph_version}`));
     state.node='SCOPE';state.edge=null;state.eventSeq=null;
     renderVersionsSelect();renderCasesDetail();renderGraph();renderFindings();renderAudit();
   }catch(err){toast(err.message,true);}
 });
 $('exportAuditBtn').addEventListener('click',downloadAudit);
 $('printBtn').addEventListener('click',()=>{if(!state.run){toast('Erst einen Prüflauf starten.',true);return;}window.print();});
 $('newCaseBtn').addEventListener('click',()=>$('newCaseDialog').showModal());
 $('cancelNewCase').addEventListener('click',()=>$('newCaseDialog').close());
 $('newCaseForm').addEventListener('submit',newCase);
 $('draftBtn').addEventListener('click',newDraft);$('validateGraphBtn').addEventListener('click',graphValidate);
 $('exportGraphBtn').addEventListener('click',exportGraph);
 $('saveGraphBtn').addEventListener('click',saveGraph);$('publishGraphBtn').addEventListener('click',publishGraph);
 window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
 // The control appears only in the pending-review report; no automatic legal sign-off.
 $('recommendationPanel').addEventListener('click',e=>{const btn=e.target.closest('[data-review]');if(btn)handleReview(btn.dataset.review);});
}
wire();boot();
