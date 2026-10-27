"""Create (or update) an account from the command line, e.g. the first admin.

    cd backend
    python scripts/create_user.py --email you@university.edu --name "Your Name" --role admin

The password is asked for interactively and never echoed or stored in shell history.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password, password_problems  # noqa: E402
from app.database.session import SessionLocal  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.services.auth_service import find_user  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--role", choices=["researcher", "supervisor", "admin"], action="append",
                        help="may be given more than once (default: researcher)")
    args = parser.parse_args()
    roles = sorted(set(args.role or ["researcher"]))
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("The passwords do not match.")
        return 1
    problems = password_problems(password)
    if problems:
        print("The password needs " + ", ".join(problems) + ".")
        return 1
    with SessionLocal() as db:
        role_rows = list(db.scalars(select(Role).where(Role.name.in_(roles))))
        if len(role_rows) != len(roles):
            print("Roles are missing from the database. Run database/schema.sql first.")
            return 1
        user = find_user(db, args.email)
        if user is None:
            user = User(email=args.email.strip().lower(), full_name=args.name, password_hash=hash_password(password), is_email_verified=True)
            db.add(user)
            action = "Created"
        else:
            user.full_name, user.password_hash, user.is_active = args.name, hash_password(password), True
            action = "Updated"
        user.roles = role_rows
        db.commit()
        print(f"{action} {user.email} with role(s): {', '.join(roles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
