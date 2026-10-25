#!/usr/bin/env python3
"""
Dazzle by Dua - Secure Administrator Management CLI

Usage:
  # List all administrators (read-only, zero secrets displayed):
  python create_admin.py --list

  # Interactive mode (prompts securely for password with confirmation):
  python create_admin.py

  # Non-interactive initial admin creation:
  python create_admin.py --username dua --email dua@dazzlebydua.com --password "SecurePass123!" --name "Dua" --role "Store Owner"

  # Reset password for an existing admin (requires explicit --reset flag):
  python create_admin.py --username dua --password "NewSecurePass123!" --reset

  # Delete an administrator account (requires interactive 'yes' confirmation):
  python create_admin.py --username dua --delete
"""

import sys
import re
import argparse
import asyncio
import getpass
import datetime
import logging
from typing import Optional, List, Dict, Any, Callable

from app.database import init_db, close_db, get_database, hash_password

logger = logging.getLogger("dazzle.admin_cli")


def validate_username(username: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9_.-]{3,30}$", username))


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def validate_password(password: str) -> bool:
    return len(password) >= 8


async def list_admins(db) -> List[Dict[str, Any]]:
    """
    Safely query and display registered administrators.
    Projection strictly excludes password hashes and secrets.
    """
    cursor = db.admins.find({}, {"password_hash": 0, "_id": 0}).sort("created_at", 1)
    admins = await cursor.to_list(length=500)

    if not admins:
        print("\nNo administrator accounts registered.\n")
        return []

    header = f"{'Username':<20} {'Email':<32} {'Role':<22} {'Name':<20} {'Created At'}"
    separator = "-" * len(header)
    print(f"\n{separator}")
    print(f"Dazzle by Dua - Registered Administrators (Total: {len(admins)})")
    print(separator)
    print(header)
    print(separator)
    for a in admins:
        u = str(a.get("username", ""))[:18]
        e = str(a.get("email", ""))[:30]
        r = str(a.get("role", ""))[:20]
        n = str(a.get("name", ""))[:18]
        c = str(a.get("created_at", "N/A"))
        print(f"{u:<20} {e:<32} {r:<22} {n:<20} {c}")
    print(f"{separator}\n")
    return admins


async def delete_admin(db, username: str, prompt_func: Callable[[str], str] = input) -> bool:
    """
    Safely delete an administrator with safeguards:
    - Refuses nonexistent accounts
    - Refuses deletion of the last remaining administrator
    - Requires explicit confirmation ('yes')
    - Never bypasses confirmation
    """
    clean_username = username.strip().lower()
    existing = await db.admins.find_one({"username": clean_username})

    if not existing:
        print(f"\n[ERROR] Administrator account '{username}' does not exist.", file=sys.stderr)
        return False

    total_admins = await db.admins.count_documents({})
    if total_admins <= 1:
        print(
            f"\n[ERROR] Cannot delete administrator '{existing['username']}'.\n"
            f"This is the only registered administrator account (total: {total_admins}).\n"
            f"The system requires at least one active administrator.\n",
            file=sys.stderr
        )
        return False

    confirm = prompt_func(
        f"\nAre you sure you want to permanently delete administrator '{existing['username']}' ({existing.get('email', '')})? "
        f"Type 'yes' to confirm: "
    ).strip()

    if confirm != "yes":
        print(f"\n[CANCELLED] Deletion cancelled. Confirmation did not match 'yes'.\n")
        return False

    res = await db.admins.delete_one({"_id": existing["_id"]})
    if res.deleted_count > 0:
        print(f"\n[SUCCESS] Successfully deleted administrator '{existing['username']}'.\n")
        return True

    return False


async def main(argv: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(
        description="Securely manage, list, create, or reset administrator accounts for Dazzle by Dua."
    )
    parser.add_argument("--list", "-l", action="store_true", help="List registered administrator accounts (read-only, secrets hidden)")
    parser.add_argument("--delete", "-d", action="store_true", help="Delete an administrator account (requires confirmation)")
    parser.add_argument("--username", "-u", type=str, help="Admin username (3-30 alphanumeric characters)")
    parser.add_argument("--email", "-e", type=str, help="Admin email address")
    parser.add_argument("--password", "-p", type=str, help="Admin password (minimum 8 characters)")
    parser.add_argument("--name", "-n", type=str, help="Admin full name (default: same as username)")
    parser.add_argument("--role", "-r", type=str, default="Store Administrator", help="Admin role (default: Store Administrator)")
    parser.add_argument("--reset", action="store_true", help="Explicitly authorize password reset if admin already exists")
    parser.add_argument("--non-interactive", action="store_true", help="Fail if any required argument is missing instead of prompting")

    args = parser.parse_args(argv)

    # 1. Validation of argument combinations
    if args.list:
        if args.delete or args.reset or args.password:
            print("Error: --list cannot be combined with mutation flags (--delete, --reset, --password).", file=sys.stderr)
            sys.exit(1)
        await init_db()
        db = get_database()
        try:
            await list_admins(db)
            return 0
        finally:
            await close_db()

    if args.delete:
        if args.reset or args.password:
            print("Error: --delete cannot be combined with --reset or --password.", file=sys.stderr)
            sys.exit(1)
        if args.non_interactive:
            print("Error: Deletion requires interactive confirmation and cannot be executed with --non-interactive.", file=sys.stderr)
            sys.exit(1)

        username = (args.username or "").strip()
        if not username:
            username = input("Enter admin username to delete: ").strip()

        if not username or not validate_username(username):
            print("Error: Username must be 3-30 characters containing only letters, numbers, hyphens, dots or underscores.", file=sys.stderr)
            sys.exit(1)

        await init_db()
        db = get_database()
        try:
            success = await delete_admin(db, username)
            if not success:
                sys.exit(1)
            return 0
        finally:
            await close_db()

    # 2. Interactive / Non-interactive admin creation & reset
    username = (args.username or "").strip()
    if not username:
        if args.non_interactive:
            print("Error: --username is required in non-interactive mode.", file=sys.stderr)
            sys.exit(1)
        username = input("Enter admin username: ").strip()

    if not validate_username(username):
        print("Error: Username must be 3-30 characters containing only letters, numbers, hyphens, dots or underscores.", file=sys.stderr)
        sys.exit(1)

    clean_username = username.lower()

    # Initialize DB connection pool
    await init_db()
    db = get_database()

    try:
        # Check if admin already exists
        escaped = re.escape(clean_username)
        existing_admin = await db.admins.find_one({
            "$or": [
                {"username": clean_username},
                {"email": {"$regex": f"^{escaped}$", "$options": "i"}}
            ]
        })

        if existing_admin and not args.reset:
            print(
                f"\n[ERROR] Administrator account '{username}' already exists!\n"
                f"For safety, this script refuses to overwrite existing accounts.\n"
                f"To update the password for this existing account, rerun with the '--reset' flag:\n"
                f"    python create_admin.py --username {username} --reset\n",
                file=sys.stderr
            )
            sys.exit(1)

        # Collect email
        email = (args.email or "").strip()
        if not email and not existing_admin:
            if args.non_interactive:
                email = f"{clean_username}@dazzlebydua.com"
            else:
                email = input(f"Enter admin email [{clean_username}@dazzlebydua.com]: ").strip()
                if not email:
                    email = f"{clean_username}@dazzlebydua.com"

        if email and not validate_email(email):
            print("Error: Invalid email format.", file=sys.stderr)
            sys.exit(1)

        # Collect password
        password = args.password or ""
        if not password:
            if args.non_interactive:
                print("Error: --password is required in non-interactive mode.", file=sys.stderr)
                sys.exit(1)
            password = getpass.getpass("Enter secure password (min 8 characters): ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                print("Error: Passwords do not match.", file=sys.stderr)
                sys.exit(1)

        if not validate_password(password):
            print("Error: Password must be at least 8 characters long.", file=sys.stderr)
            sys.exit(1)

        # Name & Role
        name = (args.name or "").strip()
        if not name:
            if existing_admin:
                name = existing_admin.get("name", username)
            else:
                name = username.capitalize()

        role = (args.role or "Store Administrator").strip()

        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        hashed_pw = hash_password(password)

        if existing_admin and args.reset:
            await db.admins.update_one(
                {"_id": existing_admin["_id"]},
                {
                    "$set": {
                        "password_hash": hashed_pw,
                        "updated_at": now_iso
                    }
                }
            )
            print(f"\n[SUCCESS] Successfully reset password for administrator '{existing_admin['username']}'.")
        else:
            admin_doc = {
                "username": clean_username,
                "email": email.lower(),
                "password_hash": hashed_pw,
                "name": name,
                "role": role,
                "created_at": now_iso
            }
            await db.admins.insert_one(admin_doc)
            print(f"\n[SUCCESS] Successfully created administrator '{clean_username}' ({email}) with role '{role}'.")

    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
