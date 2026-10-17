"""Unfinished reasoning metadata must not become publishable execution logic."""
import shutil
import subprocess

import pytest

from app.engine import execute
from app.model import HISTORICAL_CONTEXT, LEGAL, SOURCE_SHA256, seed_graph, validate_graph
from app.storage import connect, create_case, get_case, init_db, save_facts


@pytest.mark.parametrize("signal", ["transaction_classification", "effective_date_ok",
                                    "historical_valuation", "historical_sale"])
def test_unimplemented_reasoning_signal_is_rejected(signal):
    graph = seed_graph()
    next(n for n in graph["nodes"] if n["id"] == "SCOPE")["signal"] = signal
    for edge in graph["edges"]:
        if edge["source"] == "SCOPE":
            edge["guard"]["signal"] = signal
    assert any("Signal nicht zulässig" in error for error in validate_graph(graph))


@pytest.mark.parametrize("handler", ["historical_original", "historical_egi", "historical_share_sale"])
def test_unimplemented_reasoning_handler_is_rejected(handler):
    graph = seed_graph()
    next(n for n in graph["nodes"] if n["id"] == "VALUATION")["handler"] = handler
    assert any("Handler nicht unterstützt" in error for error in validate_graph(graph))


def test_learning_reference_does_not_advertise_unserved_legal_sources():
    graph = seed_graph()
    assert not validate_graph(graph)
    assert len(graph["nodes"]) == 19 and len(graph["edges"]) == 35
    assert len(SOURCE_SHA256) == 64
    assert not any(source["url"].startswith("/api/sources/wlw") for source in LEGAL.values())


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "reasoning.sqlite3"))
    init_db()
    with connect() as database:
        yield database


def test_historical_context_cannot_silently_use_current_rules(database):
    case_id = create_case(database, "Historischer synthetischer Lehrfall", context_id=HISTORICAL_CONTEXT)
    before = database.execute("SELECT count(*) FROM runs").fetchone()[0]
    with pytest.raises(ValueError, match="historischen Rechtskontext"):
        execute(database, case_id, "umwstg20-v1")
    assert database.execute("SELECT count(*) FROM runs").fetchone()[0] == before


def test_unresolved_observations_are_retained_but_block_execution(database):
    case_id = create_case(database, "Synthetischer Fall mit Gegenbeleg")
    facts = get_case(database, case_id)["facts"]
    fact = next(f for f in facts if f["key"] == "new_shares")
    fact.update(value=True, verification="confirmed", evidence_ref="SYNTHETISCH: Vertrag",
                observations=[{"value": False, "verification": "confirmed", "evidence_ref": "SYNTHETISCH: Gegenvermerk"}])
    save_facts(database, case_id, facts, "Demo-Prüfer")
    retained = next(f for f in get_case(database, case_id)["facts"] if f["key"] == "new_shares")
    assert retained["observations"][0]["value"] is False
    before = database.execute("SELECT count(*) FROM runs").fetchone()[0]
    with pytest.raises(ValueError, match="Beobachtungen erfordern eine fachliche Klärung"):
        execute(database, case_id, "umwstg20-v1")
    assert database.execute("SELECT count(*) FROM runs").fetchone()[0] == before


def test_frontend_freshness_detects_changes_to_observations():
    if not shutil.which("node"):
        pytest.skip("Node.js für die JavaScript-Prüfung nicht verfügbar.")
    # Exercise the actual pure signature function; no simulated DOM or UI claims.
    script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('app/static/app.js', 'utf8');
const definition = source.split('\\n').find(line => line.startsWith('function factSignature('));
const context = vm.createContext({});
vm.runInContext(definition, context);
const base = [{key:'new_shares',value:true,verification:'confirmed',evidence_ref:'Demo'}];
const counterevidence = structuredClone(base);
counterevidence[0].observations = [{value:false,verification:'confirmed',evidence_ref:'Gegenbeleg'}];
assert.notEqual(context.factSignature(base), context.factSignature(counterevidence));
assert.equal(context.factSignature(base), context.factSignature([{...base[0], observations:[]} ]));
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
