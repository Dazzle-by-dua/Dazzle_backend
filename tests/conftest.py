import os
import pytest

# Enforce isolated test configuration environment before app modules load
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test_environment_secret_key_minimum_32_characters_long_12345"
os.environ["INITIAL_ADMIN_USERNAME"] = "test_admin"
os.environ["INITIAL_ADMIN_PASSWORD"] = "TestAdminPass123!"
os.environ["INITIAL_ADMIN_EMAIL"] = "test_admin@dazzlebydua.com"
os.environ["INITIAL_ADMIN_NAME"] = "Dua"

TEST_ADMIN_USERNAME = "test_admin"
TEST_ADMIN_PASSWORD = "TestAdminPass123!"
TEST_ADMIN_EMAIL = "test_admin@dazzlebydua.com"
TEST_ADMIN_NAME = "Dua"


@pytest.fixture(scope="session", autouse=True)
def ensure_test_admin_seeded():
    """Ensure the isolated test admin exists in the test database for the entire test session."""
    import asyncio
    import datetime
    from app.database import init_db, get_database, hash_password

    async def _seed():
        await init_db()
        db = get_database()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        existing = await db.admins.find_one({"username": TEST_ADMIN_USERNAME})
        if not existing:
            await db.admins.insert_one({
                "username": TEST_ADMIN_USERNAME,
                "email": TEST_ADMIN_EMAIL,
                "password_hash": hash_password(TEST_ADMIN_PASSWORD),
                "name": TEST_ADMIN_NAME,
                "role": "Master Administrator",
                "created_at": now_iso
            })

    asyncio.run(_seed())
