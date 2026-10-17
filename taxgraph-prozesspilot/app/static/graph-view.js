"use strict";

const graphNavigation = {zoom:1,width:1100,height:1860,version:null};
const edgeStatusDE = {selected:'Ausgeführt · gewählt',rejected:'Ausgewertet · nicht gewählt',pending:'Gewählt · Klärung / Freigabe offen',unevaluated:'Nicht ausgewertet'};
const relationDE = {LEADS_TO:'Führt zu',TRIGGERS:'Löst aus',PROVIDES_INPUT_FOR:'Liefert Eingaben für',CONVERGES_TO:'Führt zusammen'};
function signalLabel(signal){return ({eligible_asset_type:'Qualifizierter Einbringungsgegenstand',other_consideration_ok:'Grenze sonstiger Gegenleistungen',professional_review:'Fachliche Freigabe'})[signal]||state.config?.fact_fields.find(f=>f.key===signal)?.label||signal;}

async function setGraphContext(graph){
  state.graph=graph;state.provenance=null;
  const id=graph.meta.id;
  try{
    const provenance=state.provenanceCache[id]||await api(`/api/graphs/${encodeURIComponent(id)}/provenance`);
    state.provenanceCache[id]=provenance;
    if(state.graph.meta.id===id)state.provenance=provenance;
  }catch{ /* An older server has no provenance endpoint. Never invent metadata. */ }
}
function graphSources(){
  if(!state.run)return state.config.legal_sources;
  return state.run.events[0]?.detail.legal_sources||Object.fromEntries(state.run.result.legal_sources.map(r=>[r.id,r]));
}
function legalHTML(refs){
  const sources=graphSources();
  return [...new Set(refs)].map(id=>sources[id]?`<a class="legal-link" href="${h(sources[id].url)}" target="_blank" rel="noopener noreferrer">↗ ${h(sources[id].label)}</a>`:`<p>${h(id)}: Quelle im damaligen Prüflauf nicht dokumentiert.</p>`).join('')||'<p>Keine Rechtsquelle hinterlegt.</p>';
}
function graphContextHTML(kind,id){
  const meta=state.graph.meta, provenance=state.provenance;
  const records=provenance?.[kind]?.[id]||[];
  return `<section class="inspector-section"><h4>Version und Herkunft</h4><p><strong>v${h(meta.version)} · ${h(meta.id)}</strong><br>${meta.status==='published'?'Veröffentlicht':'Entwurf'} · angelegt von ${h(meta.created_by)} am ${h(deDate(meta.created_at))}</p>${state.run?`<p>Prüflauf <code>${h(state.run.id)}</code><br>${h(deDate(state.run.finished_at))} · ${h(statusShort(state.run.status))}</p>`:'<p>Kein Prüflauf ausgewählt. Es wird keine Fallentscheidung vorausberechnet.</p>'}<p>Versionsveröffentlichung: ${meta.approved_by?`${h(meta.approved_by)} · ${h(deDate(meta.approved_at))}`:'Noch nicht erfolgt.'}</p><p class="help-text">Veröffentlichung dokumentiert die Strukturprüfung. Eine eigenständige fachliche Freigabe dieser ${kind==='edges'?'Kante':'Knotendefinition'} ist nicht erfasst.</p>${records.length?records.map(r=>`<div class="provenance-row"><strong>${h({created:'In dieser Version angelegt',changed:'Geändert',deleted:'Entfernt'}[r.change])} · Revision ${r.revision}</strong><br>${h(r.actor)} · ${h(deDate(r.at))}<p>${h(r.reason)}</p></div>`).join(''):'<p>Keine Änderungshistorie für dieses Element verfügbar.</p>'}${provenance?.snapshot_integrity===false?'<p class="audit-error">Revisions-Snapshot nicht konsistent. Herkunftsangaben nicht bestätigt.</p>':''}<p class="help-text">Namen sind protokollierte Nutzerangaben; Identität und Berufsqualifikation werden nicht verifiziert. Die Historie bezieht sich auf diese Version.</p></section>`;
}
function factsHTML(keys,evaluated){
  const facts=state.run?state.run.facts_snapshot:Object.fromEntries((state.case?.facts||[]).map(f=>[f.key,f]));
  const title=state.run?'Eingaben des eingefrorenen Prüflaufs':'Gespeicherte Fallangaben';
  const rows=keys.map(key=>{
    const f=facts[key],meta=state.config.fact_fields.find(field=>field.key===key);
    if(!f)return `<p>${h(meta?.label||key)}: nicht dokumentiert.</p>`;
    const val=f.value==null?'Unbekannt':typeof f.value==='boolean'?(f.value?'Ja':'Nein'):meta?.type==='number'?deMoney(f.value):meta?.choices?.find(c=>c.value===f.value)?.label||f.value;
    return `<div class="evidence-row ${f.verification==='confirmed'&&f.evidence_ref?'evidence-confirmed':'evidence-open'}"><strong>${h(meta?.label||key)}</strong><p>${h(val)} · ${h({confirmed:'Bestätigt',reported:'Ungeprüft',unknown:'Unbekannt'}[f.verification]||f.verification)}</p><p>Nachweis: ${h(f.evidence_ref||'Keine Nachweisreferenz verfügbar.')}</p></div>`;
  }).join('');
  return `<section class="inspector-section"><h4>${title}</h4>${!evaluated?'<p>Für diese Stelle liegt keine Auswertung vor. Die folgenden Angaben wurden hier nicht als Entscheidungsgrundlage verwendet.</p>':''}${rows||'<p>Kein Tatsachenfeld für diese Bedingung hinterlegt.</p>'}<p class="help-text">„Bestätigt“ bedeutet Nutzerbestätigung mit Referenz. Belegechtheit und individuelle Belegurheberschaft sind nicht unabhängig nachgewiesen.${!state.run&&state.dirty?' Ungespeicherte Eingaben sind hier nicht enthalten.':''}</p></section>`;
}
function inspectorEventsHTML(events){
  return `<section class="inspector-section"><h4>Zugehörige Ausführungsereignisse</h4>${events.length?events.map(e=>`<button class="inspector-event ${state.eventSeq===e.seq?'selected':''}" data-audit-seq="${e.seq}"><strong>#${e.seq} · ${h(auditTypeDE[e.event_type]||e.event_type)}</strong><span>${h(deTimestamp(e.at))} · ${h(e.detail.actor||'Akteur nicht erfasst')}</span></button>`).join(''):'<p>Keine Ereignisse für dieses Element im ausgewählten Prüflauf.</p>'}</section>`;
}
function wireInspector(){
  $('inspectorPanel').querySelectorAll('[data-inspect-edge]').forEach(b=>b.addEventListener('click',()=>selectAuditEdge(b.dataset.inspectEdge)));
  $('inspectorPanel').querySelectorAll('[data-inspect-node]').forEach(b=>b.addEventListener('click',()=>selectAuditNode(b.dataset.inspectNode,true)));
  $('inspectorPanel').querySelectorAll('[data-audit-seq]').forEach(b=>b.addEventListener('click',()=>showAuditEvent(Number(b.dataset.auditSeq))));
}
function renderInspector(){
  if(!state.graph)return;
  if(state.edge){renderEdgeInspector();return;}
  const node=state.graph.nodes.find(n=>n.id===state.node);
  if(!node){$('inspectorPanel').textContent='Kein Element ausgewählt.';return;}
  $('inspectorHeading').textContent='KNOTENPRÜFUNG';$('inspectorType').textContent=nodeKindDE[node.kind];
  const signal=state.run?.events.find(e=>e.event_type==='SIGNAL_EVALUATED'&&e.detail.node_id===node.id);
  const events=(state.run?.events||[]).filter(e=>GraphAudit.eventTarget(e,state.run?.events)?.node===node.id || (e.event_type==='EDGE_SELECTED'&&e.detail.from===node.id));
  const outgoing=state.graph.edges.filter(e=>e.source===node.id);
  $('inspectorPanel').innerHTML=`<h3>${h(node.title)}</h3><code>${h(node.id)}</code><p>${h(node.description)}</p>${node.signal?`<p>Prüfkriterium: ${h(signalLabel(node.signal))}</p>`:''}${signal?`<section class="inspector-section"><h4>Dokumentiertes Fachsignal</h4><p><strong>${h(outcomeDE[signal.detail.outcome])}</strong> · ${h(signal.detail.reason)}</p></section>`:'<p>An dieser Stelle ist kein Fachsignal ausgewertet.</p>'}${node.signal?factsHTML(state.config.signal_facts?.[node.signal]||signal?.detail.evidence?.map(e=>e.key)||[],!!signal):''}${node.handler?factsHTML(state.config.handler_facts?.[node.handler]||[],events.some(e=>e.event_type==='CALCULATION')):''}${node.kind==='HUMAN_GATE'?(reviewHTML(state.run)||'<p>Keine menschliche Entscheidung für diesen Prüflauf dokumentiert.</p>'):''}<section class="inspector-section"><h4>Mögliche Übergänge</h4>${outgoing.map(e=>`<button class="edge-choice" data-inspect-edge="${h(e.id)}"><strong>${h(e.label)}</strong><span>${h(e.id)} → ${h(e.target)}</span><span>${h(edgeStatusDE[GraphAudit.edgeAudit(state.graph,state.run,e.id).status])}</span></button>`).join('')||'<p>Abschlusszustand ohne ausgehende Kanten.</p>'}</section><section class="inspector-section"><h4>Rechtsverweise des Knotens</h4>${legalHTML(node.legal_refs)}<p>TaxGraph: keine Live-Abfrage; lokal kuratierte Verweise.</p></section>${inspectorEventsHTML(events)}${graphContextHTML('nodes',node.id)}`;
  wireInspector();
}
function renderEdgeInspector(){
  const audit=GraphAudit.edgeAudit(state.graph,state.run,state.edge),edge=audit.edge;
  const source=state.graph.nodes.find(n=>n.id===edge.source),target=state.graph.nodes.find(n=>n.id===edge.target);
  const signal=audit.signalEvent?.detail;
  const keys=signal?.evidence?.map(e=>e.key)||state.config.signal_facts?.[source.signal]||[];
  $('inspectorHeading').textContent='KANTENPRÜFUNG';$('inspectorType').textContent='Übergang';
  const condition=edge.guard.operator==='always'?'Unbedingter Folgeschritt':`${signalLabel(edge.guard.signal)} entspricht „${outcomeDE[edge.guard.value]||edge.guard.value}“. `;
  $('inspectorPanel').innerHTML=`<h3>${h(edge.label)}</h3><code>${h(edge.id)}</code><p><button class="text-button" data-inspect-node="${h(source.id)}">${h(source.title)} (${h(source.id)})</button> → <button class="text-button" data-inspect-node="${h(target.id)}">${h(target.title)} (${h(target.id)})</button></p><p>Relation: ${h(relationDE[edge.relation]||edge.relation)} <code>${h(edge.relation)}</code></p><p class="help-text">Der Relationstyp beschreibt den Zusammenhang. Die Ausführung folgt ausschließlich der gespeicherten Kantenbedingung; keine Parallelverarbeitung.</p><section class="inspector-section"><h4>Bedingung und Zweck</h4><p>${h(condition)}</p><pre class="guard-code">${h(JSON.stringify(edge.guard,null,2))}</pre><h4>Anleitung</h4><p>${h(edge.guidance||'Keine zusätzliche Anleitung hinterlegt.')}</p><h4>Fallstricke</h4><p>${h(edge.pitfalls||'Keine zusätzlichen Fallstricke hinterlegt.')}</p></section><section class="inspector-section"><h4>Auswertung im ausgewählten Prüflauf</h4><p class="edge-verdict verdict-${audit.truth.toLowerCase()}"><strong>${audit.truth}</strong> · ${h({TRUE:'Bedingung erfüllt',FALSE:'Bedingung nicht erfüllt',UNKNOWN:'Keine auswertbare Guard-Aufzeichnung'}[audit.truth])}</p><p><strong>${h(edgeStatusDE[audit.status])}</strong></p>${signal?`<p>Fachsignal: <strong>${h(outcomeDE[signal.outcome])}${signal.outcome==='unknown'?' (UNKNOWN)':''}</strong></p><p>${h(signal.reason)}</p>`:''}${signal?.outcome==='unknown'?'<p>Ein unbekannter Sachverhalt ist kein negativer Nachweis. Die Guard-Wahrheit zeigt nur, ob diese Kante zum aufgezeichneten Fachsignal passt.</p>':''}${audit.guardEvent?`<p>Guard-Prüfung #${audit.guardEvent.seq} · ${h(deTimestamp(audit.guardEvent.at))}</p>`:''}${audit.selectedEvent?`<p>Ausgewählt in Ereignis #${audit.selectedEvent.seq} · ${h(deTimestamp(audit.selectedEvent.at))}</p>`:''}<p class="help-text">Die Anzeige liest gespeicherte Backend-Ereignisse. Historische Bedingungen werden nicht mit aktuellen Fallangaben neu ausgewertet.</p></section>${factsHTML(keys,!!audit.guardEvent)}${source.kind==='HUMAN_GATE'?(reviewHTML(state.run)||'<p>Keine menschliche Freigabeentscheidung im damaligen Prüflauf dokumentiert.</p>'):''}<section class="inspector-section"><h4>Rechtsverweise von Quelle und Ziel</h4>${legalHTML([...(source.legal_refs||[]),...(target.legal_refs||[])])}<p>Keine eigenständigen Kantenbelege hinterlegt. Verknüpft sind die Rechtsquellen der beteiligten Knoten und die oben dokumentierten Fallnachweise.</p><p>TaxGraph: keine Live-Abfrage; lokal kuratierte Verweise.</p></section>${inspectorEventsHTML(audit.events)}${graphContextHTML('edges',edge.id)}`;
  wireInspector();
}
function selectAuditNode(id,center=false){
  state.edge=null;state.node=id;state.eventSeq=null;
  renderGraph();renderInspector();if(center)focusGraphNode(id);
}
function selectAuditEdge(id,center=false){
  const edge=state.graph.edges.find(e=>e.id===id);if(!edge)return;
  state.edge=id;state.node=edge.source;state.eventSeq=null;
  if(state.pathOnly&&!state.run?.result.selected_edges.includes(id))state.pathOnly=false;
  renderGraph();renderInspector();if(center)focusGraphNode(edge.source);
}
function showAuditEvent(seq){
  state.eventSeq=seq;switchTab('audit');
  $('eventFilter').value='';renderEventList();
  $('eventList').querySelector(`[data-seq="${seq}"]`)?.scrollIntoView({block:'nearest'});
}
function selectExecutionEvent(event){
  const target=GraphAudit.eventTarget(event,state.run?.events);if(!target)return;
  if(target.edge)selectAuditEdge(target.edge);else selectAuditNode(target.node);
  state.eventSeq=event.seq;switchTab('workspace');renderInspector();
  focusGraphNode(state.node);
}

function edgePath(a,b,offset=0){
  const w=242,hh=88;
  if(Math.abs(a.x-b.x)<100&&b.y>a.y){
    const sx=a.x+w/2,sy=a.y+hh,tx=b.x+w/2,ty=b.y;
    return `M ${sx} ${sy} C ${sx+offset*2} ${sy+42}, ${tx+offset*2} ${ty-42}, ${tx} ${ty}`;
  }
  const right=b.x>a.x,sx=right?a.x+w:a.x,tx=right?b.x:b.x+w,sy=a.y+hh/2,ty=b.y+hh/2,bulge=right?75:-75;
  return `M ${sx} ${sy} C ${sx+bulge+offset} ${sy+offset}, ${tx-bulge+offset} ${ty+offset}, ${tx} ${ty}`;
}
function renderGraph(){
  if(!state.graph)return;
  const nodes=Object.fromEntries(state.graph.nodes.map(n=>[n.id,n]));
  const path=new Set(state.run?.result.path||[]),parallel=new Map();
  for(const edge of state.graph.edges){const key=edge.source+'|'+edge.target;if(!parallel.has(key))parallel.set(key,[]);parallel.get(key).push(edge.id);}
  $('graphCounts').textContent=`${state.graph.nodes.length} Knoten · ${state.graph.edges.length} Kanten`;
  graphNavigation.width=Math.max(1100,...state.graph.nodes.map(n=>n.x+342));
  graphNavigation.height=Math.max(500,...state.graph.nodes.map(n=>n.y+160));
  const svg=$('edgeLayer');svg.setAttribute('viewBox',`0 0 ${graphNavigation.width} ${graphNavigation.height}`);
  svg.style.width=graphNavigation.width+'px';svg.style.height=graphNavigation.height+'px';
  let markup='<defs><marker id="arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7 Z" fill="context-stroke"/></marker></defs>';
  const ordered=[...state.graph.edges].sort((a,b)=>Number(a.id===state.edge)-Number(b.id===state.edge));
  for(const edge of ordered){
    const audit=GraphAudit.edgeAudit(state.graph,state.run,edge.id);
    if(state.pathOnly&&state.run&&!audit.selectedEvent)continue;
    const siblings=parallel.get(edge.source+'|'+edge.target),offset=(siblings.indexOf(edge.id)-(siblings.length-1)/2)*20;
    const d=edgePath(nodes[edge.source],nodes[edge.target],offset);
    markup+=`<g class="edge-group edge-${audit.status} ${state.edge===edge.id?'edge-inspected':''}"><path class="edge-path" d="${d}" marker-end="url(#arr)"/><path class="edge-hit" data-edge="${h(edge.id)}" d="${d}" role="button" tabindex="0" aria-pressed="${state.edge===edge.id}" aria-label="Kante ${h(edge.id)}: ${h(edge.label)} · ${h(edgeStatusDE[audit.status])}"><title>${h(edge.id)} · ${h(edge.label)}: ${h(edge.source)} → ${h(edge.target)}</title></path></g>`;
  }
  svg.innerHTML=markup;
  svg.querySelectorAll('[data-edge]').forEach(el=>{el.addEventListener('click',()=>selectAuditEdge(el.dataset.edge));el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectAuditEdge(el.dataset.edge);}});});
  $('nodeLayer').innerHTML=state.graph.nodes.filter(n=>!state.pathOnly||!state.run||path.has(n.id)||n.id===state.node).map(n=>`<button class="graph-node kind-${h(n.kind.toLowerCase())} ${path.has(n.id)?'path-node':''} ${!state.edge&&state.node===n.id?'selected':''}" style="left:${Number(n.x)}px;top:${Number(n.y)}px" data-node="${h(n.id)}" aria-label="${h(n.title)}; ${h(nodeKindDE[n.kind])}"><span class="node-topline"><span class="node-id">${h(n.id)}</span><span class="node-kind">${h(nodeKindDE[n.kind])}</span></span><span class="node-title">${h(n.title)}</span><span class="node-desc">${h(n.description)}</span>${path.has(n.id)?'<i class="node-current-dot" aria-hidden="true"></i>':''}</button>`).join('');
  $('nodeLayer').querySelectorAll('[data-node]').forEach(el=>el.addEventListener('click',()=>selectAuditNode(el.dataset.node)));
  $('edgeSelect').innerHTML='<option value="">Kante im Graph oder hier auswählen</option>'+state.graph.edges.map(e=>`<option value="${h(e.id)}">${h(e.id)} · ${h(e.label)} (${h(e.source)} → ${h(e.target)})</option>`).join('');
  $('edgeSelect').value=state.edge||'';
  $('pathToggle').textContent=state.pathOnly?'Ausgeführter Prüfpfad':'Alle Verbindungen';$('pathToggle').setAttribute('aria-pressed',String(state.pathOnly));
  $('lastNodeBtn').disabled=!state.run;
  const first=graphNavigation.version!==state.graph.meta.id;
  graphNavigation.version=state.graph.meta.id;
  if(first)fitGraph();else layoutGraph();
}
function layoutGraph(){
  const nav=graphNavigation,vp=$('graphViewport'),canvas=$('graphCanvas'),stage=$('graphStage');
  const width=Math.max(vp.clientWidth,nav.width*nav.zoom),height=Math.max(vp.clientHeight,nav.height*nav.zoom);
  canvas.style.width=width+'px';canvas.style.height=height+'px';
  stage.style.width=nav.width+'px';stage.style.height=nav.height+'px';stage.style.transform=`scale(${nav.zoom})`;
  stage.style.left=Math.max(0,(width-nav.width*nav.zoom)/2)+'px';stage.style.top=Math.max(0,(height-nav.height*nav.zoom)/2)+'px';
  $('zoomLevel').textContent=Math.round(nav.zoom*100)+' %';
}
function zoomGraph(next){
  const vp=$('graphViewport'),stage=$('graphStage'),old=graphNavigation.zoom;
  const x=(vp.scrollLeft+vp.clientWidth/2-parseFloat(stage.style.left||0))/old,y=(vp.scrollTop+vp.clientHeight/2-parseFloat(stage.style.top||0))/old;
  graphNavigation.zoom=Math.max(.1,Math.min(2.5,next));layoutGraph();
  vp.scrollLeft=x*graphNavigation.zoom+parseFloat(stage.style.left)-vp.clientWidth/2;
  vp.scrollTop=y*graphNavigation.zoom+parseFloat(stage.style.top)-vp.clientHeight/2;
}
function fitGraph(){
  const vp=$('graphViewport');graphNavigation.zoom=Math.max(.1,Math.min(1,(vp.clientWidth-24)/graphNavigation.width,(vp.clientHeight-24)/graphNavigation.height));
  layoutGraph();vp.scrollTo({left:0,top:0});
}
function resetGraph(){graphNavigation.zoom=1;layoutGraph();$('graphViewport').scrollTo({left:0,top:0});}
function focusGraphNode(id){
  const node=state.graph?.nodes.find(n=>n.id===id);if(!node)return;
  if(graphNavigation.zoom<.8)zoomGraph(.8);
  const vp=$('graphViewport'),stage=$('graphStage');
  vp.scrollTo({left:(node.x+121)*graphNavigation.zoom+parseFloat(stage.style.left)-vp.clientWidth/2,top:(node.y+44)*graphNavigation.zoom+parseFloat(stage.style.top)-vp.clientHeight/2});
}
function wireGraphNavigation(){
  $('fitGraphBtn').addEventListener('click',fitGraph);$('resetGraphBtn').addEventListener('click',resetGraph);
  $('zoomInBtn').addEventListener('click',()=>zoomGraph(graphNavigation.zoom*1.25));$('zoomOutBtn').addEventListener('click',()=>zoomGraph(graphNavigation.zoom/1.25));
  $('focusSelectionBtn').addEventListener('click',()=>focusGraphNode(state.node));
  $('lastNodeBtn').addEventListener('click',()=>{const id=state.run?.result.path.at(-1);if(id)selectAuditNode(id,true);});
  $('edgeSelect').addEventListener('change',e=>{if(e.target.value)selectAuditEdge(e.target.value,true);});
  const vp=$('graphViewport');let drag=null;
  vp.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('[data-node],[data-edge]'))return;drag={x:e.clientX,y:e.clientY,left:vp.scrollLeft,top:vp.scrollTop};vp.setPointerCapture(e.pointerId);vp.classList.add('panning');});
  vp.addEventListener('pointermove',e=>{if(drag){vp.scrollLeft=drag.left+drag.x-e.clientX;vp.scrollTop=drag.top+drag.y-e.clientY;}});
  const stop=()=>{drag=null;vp.classList.remove('panning');};vp.addEventListener('pointerup',stop);vp.addEventListener('pointercancel',stop);
  vp.addEventListener('keydown',e=>{if(e.target!==vp)return;if(['+','=','-','0','f','F'].includes(e.key)){e.preventDefault();if(e.key==='0')resetGraph();else if(e.key.toLowerCase()==='f')fitGraph();else zoomGraph(graphNavigation.zoom*(e.key==='-'?.8:1.25));}});
  new ResizeObserver(()=>{if(state.graph)layoutGraph();}).observe(vp);
}
