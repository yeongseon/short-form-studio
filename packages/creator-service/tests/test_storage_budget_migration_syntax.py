from pathlib import Path


def test_storage_budget_migration_follows_upload_intents() -> None:
    root = Path(__file__).resolve().parents[3]
    migration = root / "apps/api/migrations/versions/042_workspace_storage_budgets.py"
    source = migration.read_text(encoding="utf-8")
    compile(source, str(migration), "exec")
    assert 'revision: str = "042"' in source
    assert 'down_revision: str | None = "041"' in source
    assert "reserved_bytes" in source
    assert "pg_advisory_xact_lock" not in source
