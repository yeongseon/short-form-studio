"""Execute the additive user lookup index against a real, isolated SQL database."""

from collections.abc import Iterator
from io import StringIO
from pathlib import Path
from typing import Final

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

MIGRATIONS: Final = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture
def connection() -> Iterator[sa.Connection]:
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            scripts = ScriptDirectory(str(MIGRATIONS))
            with Operations.context(MigrationContext.configure(connection)):
                for revision in ("018", "029"):
                    script = scripts.get_revision(revision)
                    assert script is not None
                    script.module.upgrade()
            connection.execute(
                sa.text(
                    "INSERT INTO api_keys (user_id, key_hash) VALUES (7, 'first'), (7, 'second')"
                )
            )
            yield connection
    finally:
        engine.dispose()


def test_user_index_revision_follows_034() -> None:
    # Given the migration graph, when resolving the additive index revision.
    script = ScriptDirectory(str(MIGRATIONS)).get_revision("035")
    # Then existing media migration 034 remains its parent.
    assert script is not None
    assert script.down_revision == "034"


def test_upgrade_adds_nonunique_user_index_preserving_keys(connection: sa.Connection) -> None:
    # Given existing API keys, including multiple keys for the same user.
    script = ScriptDirectory(str(MIGRATIONS)).get_revision("035")
    assert script is not None
    # When applying the new revision.
    with Operations.context(MigrationContext.configure(connection)):
        script.module.upgrade()
    # Then user lookups have a non-unique index without changing key data.
    indexes = sa.inspect(connection).get_indexes("api_keys")
    index = next(index for index in indexes if index["name"] == "ix_api_keys_user_id")
    assert index["column_names"] == ["user_id"]
    assert not index["unique"]
    assert connection.execute(
        sa.text("SELECT user_id, key_hash FROM api_keys ORDER BY id")
    ).all() == [(7, "first"), (7, "second")]


def test_downgrade_restores_prior_schema_and_data(connection: sa.Connection) -> None:
    # Given the upgraded schema and its original index/column metadata.
    schema_query = sa.text(
        "SELECT type, name, sql FROM sqlite_master WHERE tbl_name = 'api_keys' ORDER BY name"
    )
    before_schema = connection.execute(schema_query).all()
    script = ScriptDirectory(str(MIGRATIONS)).get_revision("035")
    assert script is not None
    with Operations.context(MigrationContext.configure(connection)):
        script.module.upgrade()
        # When downgrading only the additive index revision.
        script.module.downgrade()
    # Then the original indexes, columns and key rows survive unchanged.
    assert connection.execute(schema_query).all() == before_schema
    assert connection.execute(
        sa.text("SELECT user_id, key_hash FROM api_keys ORDER BY id")
    ).all() == [(7, "first"), (7, "second")]


def test_user_index_emits_postgresql_ddl() -> None:
    # Given the production dialect in offline mode, without a database connection.
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    script = ScriptDirectory(str(MIGRATIONS)).get_revision("035")
    assert script is not None
    # When compiling the additive migration for PostgreSQL.
    with Operations.context(context):
        script.module.upgrade()
    # Then the migration creates only the intended non-unique index.
    assert output.getvalue().strip() == "CREATE INDEX ix_api_keys_user_id ON api_keys (user_id);"
