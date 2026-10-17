# MCP Phase 1: schreibgeschützte Ermittlung

Phase 1 stellt ein Kommandozeilenwerkzeug bereit, das die vom konfigurierten MCP-Server angebotenen Metadaten ermittelt. Es kann Serverinformationen, Fähigkeiten, Werkzeuge, Ressourcen, Ressourcenvorlagen und Prompts auflisten, sofern der Server diese Bereiche bekannt gibt. Das Werkzeug führt keine Werkzeuge aus, sendet keine Prompts und überträgt weder Falltatsachen noch Nachweisverweise, Datenbankinhalte oder Ausführungshistorien.

Die ermittelten Metadaten erscheinen als JSON im Terminal. Prüfe die Ausgabe, bevor du sie in ein öffentliches Issue, Protokoll oder Dokument kopierst; Beschreibungen des Servers sind externe Inhalte.

## Voraussetzungen

Benötigt wird Python 3.11 oder neuer. Installiere die Anwendungsabhängigkeiten in diesem Verzeichnis:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Aus Sicht der lokalen Webanwendung ist das MCP-SDK eine optionale Adapterabhängigkeit: Webanwendung und Graph-Engine importieren es nicht. Fehlt es, meldet das Ermittlungsskript `sdk_unavailable`.

## Zugangsdaten bereitstellen

Der Client liest `MCP_API_KEY` aus der Prozessumgebung. Das CLI liest selbst keine `.env`-Datei. Das lokale Startskript lädt `.env` für den Webserver; Compose reicht die Variable aus seiner Umgebungsdatei weiter. Für einen einzelnen CLI-Aufruf kannst du den Schlüssel an einer verdeckten Bash-Eingabeaufforderung eingeben:

```bash
bash -c '
  read -r -s -p "MCP_API_KEY: " MCP_API_KEY
  printf "\n"
  export MCP_API_KEY
  python3 scripts/discover_mcp.py
'
```

Führe dies im Verzeichnis `taxgraph-prozesspilot/` in einem privaten Terminal aus. Der Schlüssel steht weder im Befehlsverlauf noch in den Prozessargumenten. Schreibe ihn nicht in den Befehlstext, lade keine nicht vertrauenswürdige Shell-Datei und committe keine ausgefüllte `.env`-Datei. Die eingecheckte `.env.example` enthält nur einen leeren Platzhalter.

## Ergebnis und Grenzen

Der Aufruf endet nur dann erfolgreich, wenn die Ermittlung vollständig abgeschlossen wurde. Der Status unterscheidet fehlende Zugangsdaten, abgelehnte Anmeldung, Zeitüberschreitung, nicht erreichbaren Dienst, ungültige oder unvollständige Protokollantwort und erfolgreiche Verbindung. Eine erfolgreiche Verbindung bedeutet nur, dass die Metadaten vollständig ermittelt wurden; sie bedeutet nicht, dass ein Werkzeug ausgeführt oder zur Nutzung freigegeben wurde.

Für diesen Repository-Stand liegt kein Schlüssel zur Live-Ermittlung vor. Daher wurde kein Live-Katalog abgerufen und kein konkretes Werkzeug oder Schema des Servers bestätigt. Die automatisierten MCP-Tests verwenden einen HTTP-Mock und belegen Protokoll- und Sicherheitsverhalten des Adapters, nicht die Erreichbarkeit oder Fähigkeiten des Live-Servers.

Phase 2 erfordert eine gesonderte Prüfung der aktuellen Werkzeugschemata und ihres Verhaltens, der Daten, die ein Werkzeug erhalten würde, sowie einer expliziten Zuordnung zu Prozessschritten. Bis diese Prüfung erfolgt ist, dürfen keine Fallübertragung, Werkzeugausführung oder MCP-HTTP-Endpunkte in der Webanwendung ergänzt werden. Externe MCP-Ausgaben dürfen die deterministische fachliche Graphausführung nicht übersteuern.
