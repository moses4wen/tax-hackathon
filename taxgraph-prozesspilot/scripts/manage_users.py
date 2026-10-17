#!/usr/bin/env python3
"""Provision demo orgs and named users without putting passwords in shell history."""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth import create_org, create_user
from app.storage import connect, init_db


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    org = sub.add_parser("add-org")
    org.add_argument("org_id")
    org.add_argument("name")
    user = sub.add_parser("add-user")
    user.add_argument("username")
    user.add_argument("org_id")
    user.add_argument("role", choices=("viewer", "editor", "reviewer"))
    args = parser.parse_args()
    init_db()
    try:
        with connect() as c:
            if args.operation == "add-org":
                create_org(c, args.org_id, args.name)
            else:
                pwd = getpass.getpass("Password (12+ chars): ")
                again = getpass.getpass("Repeat password: ")
                if pwd != again:
                    parser.error("Passwords differ.")
                create_user(c, args.username, args.org_id, args.role, pwd)
    except (ValueError, Exception) as e:
        parser.error(str(e))
    print("Created successfully.")


if __name__ == "__main__":
    main()
