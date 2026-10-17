"""Verify an audit JSON offline: python3 scripts/verify_audit.py pruefpfad-….json."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.audit import verify_document


def main() -> int:
    parser = argparse.ArgumentParser(description="Prüfpfad offline ohne Server oder Datenbank prüfen.")
    parser.add_argument("datei", type=Path, help="Exportierte Prüfpfad-JSON-Datei")
    args = parser.parse_args()
    try:
        result = verify_document(json.loads(args.datei.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Prüfdatei kann nicht ausgewertet werden: {exc}", file=sys.stderr)
        return 1
    labels = {"graph_integrity": "Graphversion", "event_chain_integrity": "Ereignis-Hashkette",
              "facts_integrity": "Fall-Snapshot", "result_integrity": "Empfehlung",
              "context_integrity": "Quellen und Freigabenachweis", "execution_integrity": "Vollständigkeit und deterministische Wiederholung"}
    for key, label in labels.items():
        print(f"{label}: {'bestätigt' if result[key] else 'nicht bestätigt'}")
    print(result["limitations"])
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
