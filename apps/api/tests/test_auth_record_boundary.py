import hashlib
import os

import asyncpg
import pytest

from shorts_api.auth_lookup import resolve_api_key


@pytest.mark.asyncio
async def test_authentication_accepts_real_driver_record() -> None:
    url = os.environ.get("FIRST_SHORT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL endpoint required")
    connection = await asyncpg.connect(url)
    try:
        await connection.execute("CREATE TEMP TABLE api_keys (id int, user_id int, key_hash text, revoked_at timestamp)")
        await connection.execute(
            "INSERT INTO api_keys VALUES (12, 34, $1, NULL)",
            hashlib.sha256(b"test-credential").hexdigest(),
        )
        identity = await resolve_api_key("test-credential", connection)
        assert identity is not None
        assert (identity.key_id, identity.user_id) == (12, 34)
    finally:
        await connection.close()
