# Prüfbericht zum Hackathon-Prototyp

Stand: 17.10.2026. Grundlage: Quellcode, isolierte API-/SQLite-Tests und Vergleich mit der unveränderten Ausgangskopie. Keine fachliche Rechtsfreigabe und kein Nachweis einer produktiven Bereitstellung.

## Verifizierter Bestand

| Bereich | Tatsächlich vorhanden | Grenze |
| --- | --- | --- |
| Anwendung | FastAPI, Uvicorn, SQLite, statisches HTML/CSS/JavaScript; deutsche Oberfläche | Keine zusätzliche Frontend-Bibliothek; keine Rollen-/Identitätsprüfung |
| Prozessmodell | 19 Knoten, 35 Kanten; ACTION, DECISION, HUMAN_GATE, TERMINAL; deklarative Guards | Ein sequenzieller, zyklenfreier §20-spezifischer Executor; Relationstypen erzeugen keine Parallel- oder Datenflussausführung |
| Versionierung | Entwurf, Validierung, Veröffentlichung, vollständige Revisions-Snapshots und Elementherkunft | API schützt veröffentlichte Versionen; ein Datenbankadministrator bleibt technisch mächtig |
| Ausführung | Bestätigte Tatsachen mit Nachweisreferenz, yes/no/unknown, vier synthetische Musterfälle, hashgebundene Fachentscheidung | Bestätigung ist eine Nutzerangabe, keine Echtheitsprüfung des Belegs |
| Audit | Fakten-Snapshot, verwendete Graphversion, sämtliche Kandidaten-Guards, Kantenauswahl, Quellen-/Freigabe-Snapshot, Ereignis-Hashkette, JSON-Export und Offline-Prüfer | Lokale Konsistenzprüfung ohne externen Signaturanker; ältere Exporte enthalten gegebenenfalls nicht alle neuen Kontextnachweise |
| Interaktiver Auditor | Anklickbare Kanten/Knoten, Inspector, Zoom, Gesamtansicht, Verschieben, Pfadfilter, Ereignisverknüpfung | Automatisiert sind Datenprojektion und API geprüft; eine vollständige sichtbare Browserabnahme steht noch aus |
| MCP Phase 1 | Read-only CLI-Adapter mit MCP-SDK, `MCP_API_KEY` aus Prozessumgebung, vollständiger paginierter Metadaten-Ermittlung und begrenztem HTTP-Transport | Für diesen Repository-Stand fehlt ein Live-Schlüssel; kein Live-Katalog, Werkzeug oder Schema bestätigt. Phase 2, Werkzeugausführung und Falldatenübertragung sind nicht implementiert |
| Betrieb | Lokales Startskript, Windows-Skript, Dockerfile, Compose, Backup-Skript | Docker-Lauf nicht verifiziert: Docker-Daemon/OrbStack-Socket in der Prüfumgebung nicht erreichbar |

## Zuordnung der drei Denkschichten

| Schicht | Bestehende Grundlage | Noch erforderlich |
| --- | --- | --- |
| Prüfschema | Identifizierbare Knoten und bedingte Kanten derselben veröffentlichten Graphdefinition | Fachlich geprüfte zeitliche Normfassungen, explizite Pflicht-/Wahl-/Abhängigkeitsmetadaten, Übertragungsstichtag und vollständige Transaktionseinordnung |
| Subsumtion | SIGNAL_EVALUATED mit Tatsachenwerten, Nachweisreferenzen, Begründung und Rechtsverweisen | Eigenständige vierstufige Zustände SATISFIED / NOT_SATISFIED / UNKNOWN / CONFLICTED und Klärungsprozess für Gegenbelege |
| Rechtsfolgen | Deterministische Gegenleistungsgrenze und illustrative Wertdifferenz mit Audit-Ereignissen | Rechtsfolgen je Steuersubjekt/Jahr, vollständige Abhängigkeiten und selektive Neuberechnung; bislang erzeugt eine Faktenänderung einen neuen Prüflauf |

Zusätzliche Faktenfelder, `cases.context_id` und `case_facts.observations_json` sind vorbereitende, additive Datenfelder. Sie stellen noch keine implementierte Dreischicht-Fachlogik dar. Historische Kontexte und zusätzliche Beobachtungen werden vor Ausführung ausdrücklich zur Fachklärung angehalten. Nicht implementierte Signale und Berechnungshandler können nicht veröffentlicht werden.

Der bereitgestellte WLW-Lehrfall dient dem Lernen des Arbeitsablaufs eines Steuerberaters, nicht dem Nachbauen vorgegebener Rechenergebnisse. Der historische Kontext 2019/2020/2021 ist nicht als 2026-Rechtsmeinung verwendbar. Unterschiedliche Angaben zur sechs-/achtmonatigen Rückwirkung und die Wertansatzbegründung bleiben fachlich zu klären. Es wurde kein spezieller Kalle-Rechner eingebaut.

## Prioritäten nach Demonstrationswirkung

1. **MCP Phase 1 ist implementiert; Live-Katalog bleibt offen:** Das CLI liest angebotene Metadaten ausschließlich mit einem Schlüssel aus der Prozessumgebung und führt keine Werkzeuge aus. Da hier kein Schlüssel vorliegt, sind keine konkreten Live-Fähigkeiten oder Schemata bestätigt. Nach Bereitstellung eines gültigen Schlüssels müssen Werkzeuge und Schemata vor jeder Zuordnung fachlich geprüft werden. Phase 2 benötigt eine gesonderte Freigabe; Discovery ist kein Steuerrechtsdienstnachweis.
2. **Durchgängige sichtbare Abnahme:** Musterfall A ausführen, Fachentscheidung dokumentieren, erneut ausführen, Kante und Audit-Ereignis gegenseitig öffnen, historischen Lauf nach Faktenänderung prüfen, Export offline prüfen. Browserbedienung und Docker-Lauf getrennt von erfolgreichen API-Tests nachweisen.
3. **Fachliche Reichweite ehrlich darstellen:** Der bestehende Graph ist ein begrenztes Prüfschema, kein vollständiges §20-Gutachten. Zeitliche Normfassungen und unbelegte oder widersprüchliche Sachverhalte müssen vor einer breiteren Rechtsfolgenautomatisierung geklärt werden.
4. **Eine belastbare Subsumtionskette ausbauen:** Vor zusätzlichen Zahlenfällen eine vorhandene Bedingung mit Regelversion, Tatsachen-/Nachweisbezug, Konfliktklärung und Rückverfolgung bis zum Ergebnis vervollständigen. Vorherige Prüfläufe erhalten.
5. **Shadowing und TaxGraph vorbereiten:** Externe Vorschläge als Herkunftsdaten speichern und fachlich prüfen; deterministische Guards und Fachfreigaben bleiben verbindlich. Keine automatische Änderung des Rechtsgraphen durch externe Ausgaben.

## Nachweisgrenzen

Ausgeführt: `python -m pytest -q` → **85 bestanden**. Die MCP-Transport- und Sicherheitsprüfungen verwenden den offiziellen SDK-Transport mit einem lokalen HTTP-Mock; sie belegen nicht die Erreichbarkeit oder den Katalog des Live-Servers. `sh -n start-lokal.sh` und `node --check` für `app.js`, `graph-view.js` und `audit-data.js` waren erfolgreich. `docker compose config --quiet` validierte die Compose-Konfiguration; ein Docker-Build oder -Lauf wurde nicht ausgeführt.

Tests verwenden ausschließlich temporäre SQLite-Dateien und synthetische Fakten. Es wurde keine Live-MCP-Ermittlung mit einem echten Zugangsschlüssel durchgeführt; deshalb wird kein Serverkatalog behauptet. Ein vorhandenes Dockerfile, Compose-Konfigurationsprüfung oder grüner API-Test belegt keine laufende Docker-Bereitstellung. Eine vollständige sichtbare Browserabnahme ist im aktuellen Prüfstand nicht nachgewiesen.
