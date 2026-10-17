# Tax-Hackathon

## Integrated process V3

The homepage and `/prozesse` now provide the executable process library: versioned rules, negative-net-asset valuation, evidence-aware branches, organization roles and reproducible audit. The 17 observed source nodes are bound to a local normalized graph; the upstream full edge export remains unverified. Only synthetic cases. See [implementation, legal research, setup and verification limits](taxgraph-prozesspilot/docs/FUNCTIONAL-INTEGRATION.md). Legacy V1/V2 interfaces remain at `/studio` and `/fachpruefung` for historical use.


Dieses Repository enthält **prozessGraph**, einen deutschsprachigen Prototyp für einen strukturierten Ablauf zu § 20 UmwStG. Die Anwendung liegt unter [`taxgraph-prozesspilot/`](taxgraph-prozesspilot/); das bestehende Startskript und die dortige Dokumentation beschreiben den lokalen Betrieb.

Der Prototyp zeigt einen versionierten Prozessgraphen, fallbezogene Tatsachen und Nachweisverweise sowie eine prüfbare Ausführungshistorie. Veröffentlichte Graphdefinitionen, veränderlicher Fallzustand und fortlaufende Ausführungsprotokolle haben getrennte Aufgaben. Der aktuelle Ablauf bildet ein begrenztes Beispiel ab und ist weder eine vollständige Steuersoftware noch eine Steuerberatung.

Verwende ausschließlich synthetische Fälle. Gib keine Mandanten- oder sonstigen personenbezogenen Steuerdaten ein. Lies vor einer Anpassung die [Architektur und Grenzen](taxgraph-prozesspilot/docs/ARCHITEKTUR.md).

## Lokal starten

Voraussetzung: Python 3.11 oder neuer. Im Repository-Verzeichnis:

```bash
cd taxgraph-prozesspilot
./start-lokal.sh
```

Öffne <http://127.0.0.1:8080>. Beim ersten Start werden eine lokale virtuelle Umgebung und die festgelegten Anwendungsabhängigkeiten eingerichtet. SQLite-Dateien liegen unter `taxgraph-prozesspilot/data/` und sind von Git ausgeschlossen.

## Tests und statische Prüfungen

Installiere in `taxgraph-prozesspilot/` die Entwicklungsabhängigkeiten und starte die Python-Tests:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Der CI-Workflow prüft außerdem die Syntax der drei Browser-JavaScript-Dateien mit Node.js und die Shell-Syntax des Startskripts. Er baut und veröffentlicht kein Docker-Image.

## MCP-Ermittlung

Phase 1 ermittelt über die Kommandozeile ausschließlich die vom konfigurierten MCP-Server angebotenen Metadaten. Es werden keine Werkzeuge aufgerufen und keine Falldaten übertragen. Hinweise zu Zugangsdaten, Ausgabe und Grenzen späterer Integrationen stehen in [`docs/MCP-PHASE1.md`](taxgraph-prozesspilot/docs/MCP-PHASE1.md).

## Repository-Struktur

- `taxgraph-prozesspilot/app/` — FastAPI-Dienst, deterministische Graph-Engine, SQLite-Speicher und statische Weboberfläche.
- `taxgraph-prozesspilot/scripts/` — Audit-Prüfung, SQLite-Sicherung und MCP-Ermittlung.
- `taxgraph-prozesspilot/tests/` — Python- und JavaScript-Prüfungen.
- `taxgraph-prozesspilot/docs/` — Architektur, Prüfbericht und Integrationshinweise.

## Lizenz und Weiterverwendung

Für dieses Repository wurde noch keine Lizenz ausgewählt. Bedingungen für Weiterverwendung und Weiterverbreitung sind nicht festgelegt.
