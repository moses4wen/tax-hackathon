"""Online-safe SQLite backup using the stdlib sqlite3 backup API."""
from __future__ import annotations
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

source = Path(os.environ.get('DATABASE_PATH', './data/prozesspilot.sqlite3')).expanduser()
if not source.exists():
    raise SystemExit(f'Datenbank nicht gefunden: {source}')
destination = Path(sys.argv[1]) if len(sys.argv) > 1 else source.parent / 'backups' / f"prozesspilot-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.sqlite3"
destination.parent.mkdir(parents=True, exist_ok=True)
if source.resolve() == destination.resolve():
    raise SystemExit('Backup darf die Quelldatenbank nicht überschreiben.')
with sqlite3.connect(source) as src, sqlite3.connect(destination) as target:
    src.backup(target)
    if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('SQLite Integrity Check fehlgeschlagen')
print(f'Datenbanksicherung erstellt: {destination.resolve()}')
