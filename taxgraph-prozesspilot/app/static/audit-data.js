"use strict";

// Read recorded execution data only. This module never executes a guard.
(function (root) {
  function edgeAudit(graph, run, edgeId) {
    const edge = graph.edges.find(e => e.id === edgeId);
    if (!edge) throw new Error("Kante nicht gefunden.");
    if (run && run.graph_version !== graph.meta.id) throw new Error("Prüflauf und Graphversion stimmen nicht überein.");
    const events = run?.events || [];
    const guardEvent = events.find(e => e.event_type === "GUARDS_EVALUATED" &&
      e.detail.candidates?.some(candidate => candidate.edge_id === edgeId && candidate.source === edge.source));
    const candidate = guardEvent?.detail.candidates.find(c => c.edge_id === edgeId);
    const signalEvent = events.find(e => e.event_type === "SIGNAL_EVALUATED" && e.detail.node_id === edge.source);
    const selectedEvent = events.find(e => e.event_type === "EDGE_SELECTED" && e.detail.edge_id === edgeId);
    const truth = candidate?.guard_result === true ? "TRUE" : candidate?.guard_result === false ? "FALSE" : "UNKNOWN";
    const pending = !!selectedEvent && ["unknown", "pending"].includes(signalEvent?.detail.outcome);
    const status = selectedEvent ? (pending ? "pending" : "selected") : candidate ? "rejected" : "unevaluated";
    const relevant = events.filter(e => e === guardEvent || e === signalEvent || e === selectedEvent ||
      (e.event_type === "NODE_ENTERED" && (e.detail.node_id === edge.source || (selectedEvent && e.detail.node_id === edge.target))));
    return {edge, candidate, guardEvent, signalEvent, selectedEvent, truth, pending, status, events: relevant};
  }

  function eventTarget(event, events = []) {
    if (event.event_type === "EDGE_SELECTED") return {edge: event.detail.edge_id};
    const node = event.detail.node_id || event.detail.from || event.detail.terminal || event.detail.candidates?.[0]?.source;
    if (!node && event.event_type === 'RUN_STARTED') {
      const first = events.find(e => e.seq > event.seq && e.event_type === 'NODE_ENTERED');
      return first ? {node:first.detail.node_id} : null;
    }
    if (!node && ['CALCULATION','RECOMMENDATION'].includes(event.event_type)) {
      const previous = events.filter(e => e.seq < event.seq && e.event_type === 'NODE_ENTERED').at(-1);
      return previous ? {node:previous.detail.node_id} : null;
    }
    return node ? {node} : null;
  }

  const api = {edgeAudit, eventTarget};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.GraphAudit = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
