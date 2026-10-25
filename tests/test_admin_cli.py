import pytest
import asyncio
from unittest.mock import MagicMock, patch
import datetime

from app.database import init_db, get_database, hash_password
from create_admin import list_admins, delete_admin, main, validate_username, validate_email, validate_password


@pytest.fixture(autouse=True)
def setup_isolated_test_db():
    """Ensure in-memory mock database is initialized with known admin accounts for testing."""
    async def _init():
        await init_db()
        db = get_database()
        await db.admins.delete_many({})
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await db.admins.insert_many([
            {
                "username": "superadmin",
                "email": "superadmin@dazzlebydua.com",
                "password_hash": hash_password("SuperSecure123!"),
                "name": "Super Admin",
                "role": "Master Administrator",
                "created_at": now_iso
            },
            {
                "username": "subadmin",
                "email": "subadmin@dazzlebydua.com",
                "password_hash": hash_password("SubSecure123!"),
                "name": "Sub Admin",
                "role": "Store Administrator",
                "created_at": now_iso
            }
        ])

    asyncio.run(_init())


@pytest.mark.anyio
async def test_list_admins_excludes_password_hashes():
    db = get_database()
    admins = await list_admins(db)

    assert len(admins) == 2
    for a in admins:
        assert "password_hash" not in a
        assert "_id" not in a
        assert "username" in a
        assert "email" in a
        assert "role" in a
        assert "name" in a


@pytest.mark.anyio
async def test_delete_admin_successful_with_yes_confirmation():
    db = get_database()
    assert await db.admins.count_documents({}) == 2

    success = await delete_admin(db, "subadmin", prompt_func=lambda _: "yes")
    assert success is True

    remaining = await db.admins.find_one({"username": "subadmin"})
    assert remaining is None
    assert await db.admins.count_documents({}) == 1


@pytest.mark.anyio
async def test_delete_admin_aborted_when_confirmation_not_yes():
    db = get_database()
    assert await db.admins.count_documents({}) == 2

    for reject_input in ["no", "N", "YES", "y", "cancel", ""]:
        success = await delete_admin(db, "subadmin", prompt_func=lambda _: reject_input)
        assert success is False

    remaining = await db.admins.find_one({"username": "subadmin"})
    assert remaining is not None
    assert await db.admins.count_documents({}) == 2


@pytest.mark.anyio
async def test_delete_admin_refuses_nonexistent_account():
    db = get_database()
    success = await delete_admin(db, "ghost_account", prompt_func=lambda _: "yes")
    assert success is False

    # Attempting deletion by email must be refused (strictly username lookup only)
    success_email = await delete_admin(db, "subadmin@dazzlebydua.com", prompt_func=lambda _: "yes")
    assert success_email is False

    assert await db.admins.count_documents({}) == 2


@pytest.mark.anyio
async def test_delete_admin_prevents_deleting_last_administrator():
    db = get_database()
    # Delete subadmin first so only 1 admin remains
    await db.admins.delete_one({"username": "subadmin"})
    assert await db.admins.count_documents({}) == 1

    # Attempting to delete the last admin (superadmin) must fail even if confirmed
    success = await delete_admin(db, "superadmin", prompt_func=lambda _: "yes")
    assert success is False

    # Verify account was preserved
    last_admin = await db.admins.find_one({"username": "superadmin"})
    assert last_admin is not None
    assert await db.admins.count_documents({}) == 1


@pytest.mark.anyio
async def test_main_cli_list_execution(capsys):
    ret = await main(["--list"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "Dazzle by Dua - Registered Administrators" in captured.out
    assert "test_admin" in captured.out or "superadmin" in captured.out
    assert "SuperSecure123!" not in captured.out
    assert "$2b$" not in captured.out
    assert "password_hash" not in captured.out


@pytest.mark.anyio
async def test_main_cli_delete_rejects_non_interactive():
    with pytest.raises(SystemExit) as exc_info:
        await main(["--username", "subadmin", "--delete", "--non-interactive"])
    assert exc_info.value.code == 1


@pytest.mark.anyio
async def test_main_cli_conflicting_arguments():
    # Combining --list and --delete
    with pytest.raises(SystemExit) as exc_info:
        await main(["--list", "--delete"])
    assert exc_info.value.code == 1

    # Combining --delete and --reset
    with pytest.raises(SystemExit) as exc_info:
        await main(["--username", "subadmin", "--delete", "--reset"])
    assert exc_info.value.code == 1
