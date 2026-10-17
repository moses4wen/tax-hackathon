# Technische Architektur und Audit-Modell

## Ausführung statt Zeichnung

Der Browser ist kein Ausführungsorgan: `app/engine.py` lädt eine **veröffentlichte Graphversion** aus SQLite und traversiert ihre gespeicherten Knoten und Kanten. Die Graphdefinition ist die Autoritätsquelle. `graph_nodes` und `graph_edges` verwenden zusammengesetzte Fremdschlüssel `(version_id,node_id)`; eine Kante kann nicht auf Knoten einer anderen Version verweisen.

### Typen

| Knotentyp | Semantik | Zulässige Edge Outcomes |
| --- | --- | --- |
| ACTION | Einmaliger definierter Schritt (z. B. Bewertung) | `always` |
| DECISION | Deterministische Bedingung mit verifiziertem Signal | `yes`, `no`, `unknown` |
| HUMAN_GATE | Status einer dokumentierten, hashgebundenen Fachentscheidung | `approved`, `pending`, `rejected` |
| TERMINAL | Ergebnis/Handlungsaufforderung | keine |

Knoten enthalten `id`, `kind`, `title`, `description`, `x`, `y`, `signal`, `legal_refs`, optional `handler`. Kanten enthalten `id`, `source`, `target`, `relation`, `outcome`, `label`, `guard`, `guidance`, `pitfalls`.

Ein `guard` ist kein JavaScript, sondern eine kleine fest verdrahtete deklarative Entscheidung: `{"operator":"eq","signal":"new_shares","value":"yes"}` oder `{"operator":"always"}`. Die Engine vergleicht den Guard mit dem Resultat des Signal-Resolvers; keine beliebigen Funktionen oder Code-Evaluierung. Die Graphstruktur wird vor jeder Veröffentlichung validiert. Der derzeitige Engine-Adapter ist **§20-spezifisch**, kein generischer BPMN-Ausführer.

Die Resultate `OUTSIDE`, `BLOCKED`, `MISSING` und `PENDING` sind fachlich verschieden. Eine positive Freigabe wird zusätzlich außerhalb des editierbaren Graphen gegen die Pflichtprüfungen abgesichert. Eine Graphänderung kann diese Pflichtprüfungen somit nicht stillschweigend umgehen.

## Datenbanken

- `graph_versions`: Status `draft|published`, Checksumme, Version, Freigabe-Metadaten.
- `graph_nodes`, `graph_edges`: kompletter Graph je Version.
- `graph_revision_log`: vollständige Snapshots pro Bearbeitung mit Änderungsgrund und strukturellem Diff; über `/api/graphs/{id}/revisions` als Metadaten einsehbar.
- `cases`, `case_facts`: synthetische Fallakten; `verification=unknown|reported|confirmed` und `evidence_ref`.
- `case_reviews`: dokumentierte Fachentscheidungen, gebunden an Fall-ID + Graphversion + Fallfakten-Hash.
- `runs`: Snapshot der Fakten, Graphchecksumme, Empfehlung, Beginn/Ende, Status.
- `run_events`: alle Knotenbetritte, Evaluierungen der möglichen Kanten, gewählten Kanten und Rechenergebnisse; Hashkette je Run.
- `activity_events`: globale Aktivitätshistorie für Fall- und Graphänderungen; Hashkette.

## Audit und Reproduzierbarkeit

`/api/runs/{run_id}/audit` exportiert Run, alle Run-Events, verwendeten Graph (alle Nodes/Edges), Graphrevisions-Metadaten, Prüfsummen und Rechtsverweise. Die Prüfsummen sind für jedes Run getrennt: Graph-Checksumme, eingefrorener Fakten-Hash, vollständiger Empfehlungs-Hash, Ereignis-Hashkette. Bei jedem `GUARDS_EVALUATED`-Event werden **alle** möglichen ausgehenden Kanten samt true/false Auswertung erfasst, nicht nur die ausgewählte.

**Historical Replay** bedeutet das Anzeigen gespeicherter Ereignisse; eine neue Ausführung ist ein neuer Run und verändert den historischen Run nicht. Die deterministische Engine liefert mit denselben bestätigten Fakten und derselben unveränderten Graphversion dieselbe Pfadentscheidung. Zeitstempel und Run-IDs ändern sich natürlich.

Hashketten in einer frei administrierbaren SQLite-Datei stellen **keine** revisionssichere, extern zertifizierte Archivierung dar. Ein Datenbankadministrator kann auch die Ketten neu schreiben. Keine externe Signatur/Zeitstempelautorität. Es existiert kein Rollen-/Identitätsnachweis, weder für Fachprüfer noch Benutzer (nur optionale gemeinsame Demo-Anmeldung via HTTP Basic Auth).

## Mandanten- und Datenschutzgrenzen

Es gibt absichtlich keine Dateiuploads, Mikrofon- oder Bildschirmaufnahmen, OCR, DATEV-Anbindung oder Live-LLM-Extraktion. Testfälle sind synthetisch, Belegreferenzen Text. Damit werden personenbezogene Steuerdaten in diesem Prototyp vermieden — eine allgemeine DSGVO-Konformität wird **nicht** behauptet. Für echtes Shadowing von Steuerkanzleiprozessen müssen Datensparsamkeit, Berufsverschwiegenheit, Beschäftigtendatenschutz und Auftragsverarbeitung gesondert umgesetzt werden.

## Rechtsgrundlagen und Einschränkungen

- [§ 20 UmwStG 2006](https://www.gesetze-im-internet.de/umwstg_2006/__20.html)
- [§ 22 UmwStG 2006](https://www.gesetze-im-internet.de/umwstg_2006/__22.html)
- [BMF Anwendung des Umwandlungssteuergesetzes, 02.01.2025](https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Steuerarten/Koerperschaftsteuer_Umwandlungssteuer/2025-01-02-umwStE.pdf?__blob=publicationFile)

Im Graph sind nur für das Mustergeschäft ausgewählte Teilfragen strukturiert. Weitere Prüfungen können erforderlich sein, z. B. Gesellschaftsrecht/UmwG, steuerlicher Übertragungsstichtag, Einlagen/Entnahmen, § 22 Nachweisführung, Umwandlungen ausländischer Rechtsträger oder Grunderwerbsteuer. Der Buchwert-/Gegenleistungsvergleich ist eine vereinfachte **illustrative** Berechnung, kein automatisches Steuergutachten. Das Modell ersetzt nicht die fallbezogene Rechtsprüfung durch eine fachlich befugte Person.
