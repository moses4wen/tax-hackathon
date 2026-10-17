"""Organization-scoped, server-enforced RBAC for the synthetic demo.

Production uses distinct HTTP Basic identities over HTTPS, with scrypt-hashed
passwords in SQLite. This is NOT SSO, a tax-professional qualification check, or
a production-grade identity provider. User provisioning is CLI-only.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import re
import sqlite3
from dataclasses import dataclass

from fastapi import HTTPException, Request

from .storage import connect

ROLES = ("viewer", "editor", "reviewer")
WRITE_ROLES = ("editor", "reviewer")
_AUTH_SALT_BYTES = 16
_SCRYPT_N = 2**14


@dataclass(frozen=True)
class Principal:
    username: str
    org_id: str
    role: str


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        raise ValueError("Passwort muss 12 bis 256 Zeichen enthalten.")
    salt = os.urandom(_AUTH_SALT_BYTES)
    hashed = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + hashed.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = stored.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (16384, 8, 1):
            return False
        result = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt),
                               n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(result, bytes.fromhex(expected))
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False


def authenticate(header: str) -> Principal | None:
    if not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (binascii.Error, ValueError, UnicodeError):
        return None
    with connect() as c:
        row = c.execute("SELECT username, org_id, role, password_hash FROM app_users "
                        "WHERE username=? AND active=1", (username,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return Principal(row["username"], row["org_id"], row["role"])


def local_principal() -> Principal:
    return Principal(os.getenv("APP_USER", "Demo Reviewer"), "demo", "reviewer")


def current(request: Request) -> Principal:
    identity = getattr(request.state, "principal", None)
    if identity is None:
        raise HTTPException(401, detail="Authentifizierung erforderlich.")
    return identity


def require_role(request: Request, *roles: str) -> Principal:
    identity = current(request)
    if identity.role not in roles:
        raise HTTPException(403, detail="Für diese Aktion fehlt die Berechtigung.")
    return identity


def graph_access(request: Request, c: sqlite3.Connection, version_id: str) -> dict:
    identity = current(request)
    row = c.execute("SELECT * FROM graph_versions WHERE id=? AND org_id=?",
                    (version_id, identity.org_id)).fetchone()
    if row is None or (identity.role == "viewer" and row["status"] != "published"):
        raise HTTPException(404, detail="Prozess nicht gefunden.")
    return dict(row)


def case_access(request: Request, c: sqlite3.Connection, case_id: str) -> dict:
    row = c.execute("SELECT * FROM cases WHERE id=? AND org_id=?",
                    (case_id, current(request).org_id)).fetchone()
    if row is None:
        raise HTTPException(404, detail="Fall nicht gefunden.")
    return dict(row)


def run_access(request: Request, c: sqlite3.Connection, run_id: str) -> dict:
    row = c.execute("SELECT runs.* FROM runs JOIN cases ON cases.id=runs.case_id "
                    "WHERE runs.id=? AND cases.org_id=?", (run_id, current(request).org_id)).fetchone()
    if row is None:
        raise HTTPException(404, detail="Prüflauf nicht gefunden.")
    return dict(row)


def create_org(c: sqlite3.Connection, org_id: str, label: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,47}", org_id):
        raise ValueError("Org-ID: 3–48 Zeichen, Kleinbuchstaben, Zahlen, Bindestrich.")
    if not 2 <= len(label.strip()) <= 120:
        raise ValueError("Organisationsname ungültig.")
    from .storage import now, seed_cases, uid, write_graph
    from .model import seed_graph
    c.execute("INSERT INTO orgs(id,name,created_at) VALUES(?,?,?)", (org_id, label.strip(), now()))
    write_graph(c, uid("g"), "org/" + org_id + "/umwstg20", 1, seed_graph(),
                "published", "Systemdemo", "Synthetisches Referenzmodell", org_id=org_id)
    seed_cases(c, org_id=org_id)


def create_user(c: sqlite3.Connection, username: str, org_id: str, role: str, password: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", username):
        raise ValueError("Benutzername: 3–64 Buchstaben/Ziffern/._-.")
    if role not in ROLES:
        raise ValueError("Rolle muss viewer, editor oder reviewer sein.")
    if not c.execute("SELECT 1 FROM orgs WHERE id=?", (org_id,)).fetchone():
        raise ValueError("Organisation existiert nicht.")
    from .storage import now
    c.execute("INSERT INTO app_users(username,org_id,role,password_hash,active,created_at) "
              "VALUES(?,?,?,?,1,?)", (username, org_id, role, hash_password(password), now()))


def capabilities(identity: Principal) -> dict:
    return {"create_process": identity.role == "editor",
            "edit_process": identity.role in WRITE_ROLES,
            "publish_process": identity.role == "reviewer",
            "edit_case": identity.role in WRITE_ROLES,
            "approve_case": identity.role == "reviewer"}
