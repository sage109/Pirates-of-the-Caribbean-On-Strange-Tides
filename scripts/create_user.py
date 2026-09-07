#!/usr/bin/env python3
"""
scripts/create_user.py

Local/self-hosted account provisioning. On Streamlit Community Cloud this
script cannot reach the deployed app's database (no shell access there) --
use the in-app first-run setup form instead (shown automatically while
`user_count() == 0`), exactly as documented for the sibling investment
dashboard project.

Usage:
    python3 scripts/create_user.py --username jane --role accountant
    python3 scripts/create_user.py --username admin --role admin
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.database import init_db
from services.auth import ROLES, create_user, ensure_users_table


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a NYASHA AI user account (local/self-hosted use only).")
    parser.add_argument("--username", required=True)
    parser.add_argument("--role", choices=ROLES, default="viewer")
    args = parser.parse_args()

    init_db()
    ensure_users_table()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        raise SystemExit(1)

    create_user(args.username, password, args.role)
    print(f"Created user '{args.username}' with role '{args.role}'.")


if __name__ == "__main__":
    main()
