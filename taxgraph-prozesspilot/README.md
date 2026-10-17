# prozessGraph — § 20 UmwStG

**Lauffähiger Hackathon-Prototyp:** deutschsprachige Web-Anwendung mit persistiertem, typisiertem Prozessgraphen, deterministischer Ausführung, fallbezogenen Nachweisreferenzen, Versionierung und prüfbarem Ereignisprotokoll.

> **Wichtig:** Ausschließlich für synthetische/erfundene Fälle. Dies ist kein Produktivsystem für Mandantendaten, keine Steuerberatung und kein Gutachten. Es gibt **keine Live-Anbindung an TaxGraph**. Ein separates MCP-CLI kann mit einem privat gesetzten `MCP_API_KEY` Servermetadaten ermitteln; es führt keine Werkzeuge aus und überträgt keine Falldaten. Für diesen Repository-Stand liegt kein Schlüssel zur Live-Ermittlung vor, daher sind konkrete Serverwerkzeuge und Schemata nicht bestätigt. Die Freigabeidentität wird protokolliert, aber nicht berufsrechtlich verifiziert.

## 1. Schnellstart lokal (macOS/Linux)

Voraussetzung: **Python 3.11 oder neuer** und Internetzugang für das einmalige Installieren der in `requirements.txt` festgelegten Python-Abhängigkeiten.

```bash
unzip prozessgraph-hackathon.zip
cd taxgraph-prozesspilot
./start-lokal.sh
```

Dann **http://127.0.0.1:8080** im Browser öffnen. Der Server wird mit `Ctrl+C` beendet. Die SQLite-Datenbank bleibt unter `data/prozesspilot.sqlite3` erhalten.

Alternative ohne Startskript:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.server:app --host 127.0.0.1 --port 8080
```

Für Windows (PowerShell): `./start-windows.ps1` oder die Befehle der entsprechenden Abschnitte in [README-ZH.md](README-ZH.md) verwenden.

## 2. Docker: lokal oder auf einem Server

Voraussetzung: Docker + Docker Compose Plugin.

```bash
cp .env.example .env
# In .env vor dem öffentlichen Hosting unbedingt APP_ENV=production,
# APP_PASSWORD (mindestens 16 Zeichen) und ggf. APP_USER setzen.
docker compose up --build -d
```

Danach **http://127.0.0.1:8080** öffnen. `docker compose logs -f prozesspilot` zeigt die Serverlogs. Der Docker-Volume `prozesspilot_data` überlebt Neustarts und Container-Neuerstellungen.

### Hosting / HTTPS

Das Standard-Compose veröffentlicht den Dienst absichtlich **nur auf 127.0.0.1**. Für einen eigenen VPS: Reverse Proxy (z. B. Caddy/Nginx) auf dieselbe Maschine setzen, HTTPS erzwingen und `APP_ENV=production` / ein starkes Passwort verwenden. Beispiel Caddy-Konfiguration nach DNS- und TLS-Setup:

```caddyfile
prozessgraph.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Wenn die Hosting-Plattform bereits HTTPS bereitstellt und einen offenen Container-Port benötigt, `BIND_ADDRESS=0.0.0.0` setzen und die Plattform-Zugriffskontrollen verwenden. Ohne HTTPS **kein öffentliches Hosting**; HTTP Basic Auth allein schützt keine Zugangsdaten während der Übertragung. Eine gemeinsame Demo-Anmeldung ist keine mandantenfähige Benutzerverwaltung.

**Öffentlicher Demo-Modus ohne Login:** Mit `APP_ENV=local`, leerem `APP_PASSWORD` und `APP_DEMO_ROLE_SWITCH=1` zeigt die Oberfläche einen Rollenwähler für Leser, Bearbeiter und Fachprüfer. `APP_LOCAL_ROLE=editor` setzt die Startrolle. Alle Besucher teilen sich denselben synthetischen Demo-Arbeitsbereich; Änderungen sind für alle sichtbar. Nur mit vollständig erfundenen Fällen verwenden. Im Produktivmodus ist die Rollenauswahl deaktiviert.

**Persistenz:** Bei Plattform-Hosting ein dauerhaftes Volume nach `/data` mounten. Ohne dauerhaftes Volume gehen SQLite-Daten bei einer neuen Bereitstellung verloren.

## 3. Bedienung der Web-App

1. Unter **Fallakten** einen synthetischen Musterfall A–D auswählen oder eine neue Fallakte anlegen.
2. Unter **Sachverhalt** die Tatsachen angeben (`Ja`, `Nein`, `Unbekannt`) und zwischen **Ungeprüft** und **Bestätigt** unterscheiden. Bestätigte Angaben benötigen eine Nachweisreferenz oder einen Aktenvermerk. Die Referenz ist kein Beleg-Upload und prüft nicht die Echtheit des Dokuments.
3. Auf **Prüfung ausführen** klicken. Der Server führt den veröffentlichten Prozessgraphen aus. Die benutzten Knoten und Kanten werden hervorgehoben.
4. Unter **Prüfergebnis** und **Prüfpfad & Bericht** Handlungsempfehlung, offene Nachweise, § 20/§ 22 Rechtsgrundlagen und die komplette Ereigniskette einsehen. Der Bericht lässt sich drucken; der Audit-Export ist JSON.
5. Ein vollständig durchlaufener Fall endet zunächst mit **Freigabe offen**. Eine fachliche Entscheidung (Freigabe oder Ablehnung) wird dokumentiert; eine neue Ausführung berücksichtigt diese Entscheidung nur für dieselben Fallfakten und dieselbe Graphversion.
6. Unter **Prozessmodell verwalten** einen **Entwurf** erstellen, JSON für Knoten/Kanten editieren, Struktur prüfen, Änderung begründen, den Entwurf speichern und anschließend veröffentlichen. Veröffentlichte Versionen werden nicht überschrieben; ältere Prüfläufe bleiben ihrer ursprünglichen Version zugeordnet.

### Testfälle (beim ersten Start automatisch erzeugt)

| Fall | Variation | Erwarteter Auswertungspfad |
| --- | --- | --- |
| A | Alle definierten Voraussetzungen mit synthetischen Belegreferenzen bestätigt | Fachliche Freigabe ausstehend |
| B | Funktional wesentliche Betriebsgrundlage nicht übertragen | Anwendungsbereich § 20 zu prüfen |
| C | Neue Geschäftsanteile nur behauptet, ohne Bestätigung | Nachweise nachfordern |
| D | Verkauf neu erhaltener Anteile geplant | Wie A, aber § 22 Risikohinweis |

## 4. Backend & Datenhaltung

- **FastAPI + Uvicorn**; lokale statische HTML/CSS/JS-Oberfläche, ohne CDN oder Frontend-Build.
- **SQLite** (`WAL`-Modus, Fremdschlüssel aktiv) speichert Graphversionen, vollständige Nodes/Edges, Graph-Revisions-Snapshots, Fälle, Fakten, Freigaben, Prüfläufe und Audit-Events.
- **Deterministische Graph-Engine**, die für jedes `DECISION`-Signal genau `yes` / `no` / `unknown` auswählt, **ohne eval() oder LLM-gesteuerte Ausführung**. `HUMAN_GATE` verwendet `approved` / `rejected` / `pending`.
- **Prozess-Audit**: Jeder besuchte Node, alle in Betracht gezogenen Edges, Guard-Ergebnisse, ausgewählte Übergänge, Berechnungen und das Ergebnis werden als Run-Events gespeichert. Ketten-Hashes, die aktuelle Graph-Checksumme, Fakten-Snapshot-Hash und Empfehlungs-Hash können geprüft werden.
- **Graph-Audit**: neue Draft-Versionen speichern bei jeder Änderung einen vollständigen Snapshot mit Akteur, Grund und Node-/Edge-Diff. Veröffentlichte Graphen bleiben bei Änderungen über die API unveränderlich.
- **Offizielle Rechtsgrundlagen:** § 20 und § 22 UmwStG 2006 sowie der BMF-Umwandlungssteuererlass vom 02.01.2025. Automatische Rechtsaktualisierung und TaxGraph-Live-API **nicht implementiert**.

Weitere Informationen: [Architektur & Grenzen](docs/ARCHITEKTUR.md) und [MCP Phase 1: schreibgeschützte Ermittlung](docs/MCP-PHASE1.md). OpenAPI-Dokumentation: `/api/docs` (geschützt, falls APP_PASSWORD gesetzt).

### Sicherung der Datenbank

Während der lokale Server laufen darf:

```bash
python3 scripts/backup_sqlite.py
```

Dies schreibt einen konsistenten SQLite-Backup in den Ordner `data/backups/`. Bei Docker lässt sich dieselbe Prozedur über `docker compose exec prozesspilot python scripts/backup_sqlite.py` verwenden, **wenn** dieses Skript im Image vorhanden ist. Docker enthält das Skript unter `/opt/prozesspilot/scripts/` (Dockerfile kopiert `scripts/`). Um einen Backup aus dem Docker-Volume auf den Host zu kopieren, `docker cp` oder einen Volume-Backup-Prozess nutzen.

## 5. Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

Die Tests laufen mit isolierten temporären SQLite-Datenbanken und prüfen u. a. alle vier Fälle, die Auswertung der Gegenleistungsgrenze, Human Gate, Graphversionierung, Graph-/Run-Kettenintegrität, gezielte Manipulationsversuche und die MCP-Ermittlung über einen HTTP-Mock. Eine vollständige sichtbare Browser-Abnahme ist nicht nachgewiesen.

## 6. Nicht Teil des MVP

Kein OCR, kein Screen Recording/Shadowing, keine DATEV-Integration, keine TaxGraph-Live-API, keine MCP-Werkzeugausführung oder Übertragung von Falldaten, keine Mandanten-Uploads, keine Identitäts- oder Rollenprüfung, kein unveränderlicher externer Audit-Anker, keine automatisierte § 20-Gesamtprüfung aller denkbaren Umwandlungen. Rechts- und Steuerentscheidungen sind stets fachlich zu bestätigen.

**Lizenz/Nutzung:** Hackathon-Demonstrator. Vor einer Verbreitung, öffentlichem Hosting oder Nutzung von echten Mandantendaten die Nutzungsrechte, datenschutzrechtlichen Rollen und technischen Sicherheitsmaßnahmen separat prüfen.
