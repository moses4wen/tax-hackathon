"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {edgeAudit,eventTarget} = require('../app/static/audit-data.js');
const cases = JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
let checks = 0;
function check(value){assert.ok(value);checks++;}
for(const doc of Object.values(cases)){
  const snapshot = JSON.stringify(doc);
  for(const edge of doc.graph.edges){
    const audit = edgeAudit(doc.graph,doc.run,edge.id);
    const selected = doc.run.events.find(e=>e.event_type==='EDGE_SELECTED'&&e.detail.edge_id===edge.id);
    check(!!audit.selectedEvent===!!selected);
    if(audit.candidate)check(audit.truth===(audit.candidate.guard_result?'TRUE':'FALSE'));
    else check(audit.truth==='UNKNOWN'&&audit.status==='unevaluated');
  }
  check(JSON.stringify(doc)===snapshot);
}
const a=cases.A,c=cases.C;
check(edgeAudit(a.graph,a.run,'E_REVIEW_PENDING').status==='pending');
check(edgeAudit(c.graph,c.run,'E_SHARES_YES').truth==='FALSE');
check(edgeAudit(c.graph,c.run,'E_SHARES_YES').signalEvent.detail.outcome==='unknown');
check(edgeAudit(c.graph,c.run,'E_SHARES_UNKNOWN').truth==='TRUE');
check(edgeAudit(c.graph,c.run,'E_SHARES_UNKNOWN').status==='pending');
check(edgeAudit(c.graph,c.run,'E_APPLICATION_YES').status==='unevaluated');
check(edgeAudit(c.graph,null,'E_SHARES_YES').truth==='UNKNOWN');
const altered=structuredClone(c.graph);altered.meta.id='different-version';
assert.throws(()=>edgeAudit(altered,c.run,'E_SHARES_YES'),/Graphversion/);checks++;
const selection=c.run.events.find(e=>e.event_type==='EDGE_SELECTED'&&e.detail.edge_id==='E_SHARES_UNKNOWN');
check(eventTarget(selection).edge==='E_SHARES_UNKNOWN');
const guards=c.run.events.find(e=>e.event_type==='GUARDS_EVALUATED'&&e.detail.candidates.some(x=>x.edge_id==='E_SHARES_YES'));
check(eventTarget(guards).node==='SHARES');
for(const event of a.run.events)check(!!eventTarget(event,a.run.events));
console.log(`${checks} Prüfungen mit echten API-Prüfläufen bestanden.`);
