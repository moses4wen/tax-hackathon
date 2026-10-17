# Änderungsprotokoll

## Functional Integration V3 - 17.10.2026

- Integrated current process library and version-pinned legal orchestration; original V1/V2 executors retained.
- 17 source-node bindings, explicit normalized DAG, four-state guards, immutable source import and case/run review snapshots.
- BMF 20.19/20.19a minimum valuation, negative-net-asset uplift and explicit actual-date fallback.
- Organization/role checks, stale-write protection, publication reference tests and replayable learning demonstration.
- Verification and external-source limitations documented in docs/FUNCTIONAL-INTEGRATION.md.

## Unveröffentlicht — 17.10.2026

- Auditprüfung um vollständige Ereignisfolge, deterministische Wiederholung, eingefrorene Quellen und menschliche Fachentscheidung erweitert; eigenständiger JSON-Prüfer unter `scripts/verify_audit.py`.
- Fehlende Nachweisreferenzen bleiben unbekannt; Gegenleistungsgrenze wird nicht auf einen unzulässigen Cent aufgerundet; unvollständige positive Prüfpfade werden gesperrt.
- Interaktive Knoten-/Kantenprüfung, dokumentierte TRUE/FALSE/UNKNOWN-Guards, Ereignisverknüpfung, Elementherkunft, Zoom, Gesamtansicht und Pfadfilter ergänzt.
- Vorbereitende Kontext-/Beobachtungsfelder additiv in SQLite erhalten. Nicht implementierte historische Signale/Handler und nicht erreichbare PDF-Quellenlinks werden nicht als verfügbare Funktion angeboten.
- Historische Kontexte und noch nicht ausgewertete zusätzliche Beobachtungen vor Prüflaufanlage zur Fachklärung angehalten; kein spezieller historischer Zahlenrechner.
- Gespeicherte zusätzliche Beobachtungen bleiben beim Bearbeiten und beim impliziten Speichern vor Ausführung erhalten; die Oberfläche weist auf Klärungsbedarf hin und erkennt entsprechende Änderungen als veralteten Prüfstand.
- MCP Phase 1 als read-only CLI-Adapter mit offiziellem MCP-SDK ergänzt. Der Schlüssel wird nur aus `MCP_API_KEY` der Prozessumgebung gelesen; Discovery listet angebotene Metadaten, begrenzt Transport und Seitenabfragen, redigiert Schlüsselwerte und ruft keine Werkzeuge auf. Live-Katalog und Werkzeugschemata sind mangels Live-Schlüssel nicht bestätigt; Phase 2 und Falldatenübertragung bleiben nicht implementiert.
- Offline-MCP-Tests mit echtem SDK-HTTP-Transport und lokalem HTTP-Mock ergänzt; insgesamt 85 Python-/API-/JavaScript-Harness-Tests bestanden. Startskript- und JavaScript-Syntax sowie Compose-Konfiguration geprüft. Eine vollständige sichtbare Browserabnahme und ein Docker-Lauf sind nicht nachgewiesen.
- Prüfbericht mit belegtem Bestand, aktuellen Nachweisgrenzen und nächsten Hackathon-Schritten unter `docs/PRUEFBERICHT.md` ergänzt.
