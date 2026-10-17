from io import StringIO
from pathlib import Path
from typing import Final

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

MIGRATIONS: Final = Path(__file__).resolve().parents[1] / "migrations"


def test_spend_reservation_revision_follows_owned_reservations() -> None:
    # Given the migration graph, when resolving spend reservations.
    script = ScriptDirectory(str(MIGRATIONS)).get_revision("038")

    # Then it extends the existing task-owned reservation ledger.
    assert script is not None
    assert script.down_revision == "037"


def test_spend_reservation_migration_emits_expected_postgresql_columns() -> None:
    # Given the production dialect in offline mode.
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    script = ScriptDirectory(str(MIGRATIONS)).get_revision("038")
    assert script is not None

    # When compiling the additive migration.
    with Operations.context(context):
        script.module.upgrade()

    # Then aggregate and owner ledgers both store conservative estimated spend.
    ddl = output.getvalue()
    assert "reserved_estimated_cost_usd" in ddl
    assert "estimated_cost_usd" in ddl
    assert "billable_unknown" in ddl


def test_provider_attempt_revision_follows_spend_reservations() -> None:
    script = ScriptDirectory(str(MIGRATIONS)).get_revision("039")

    assert script is not None
    assert script.down_revision == "038"
