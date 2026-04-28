from pathlib import Path


def test_usage_migration_file_compiles() -> None:
    root = Path(__file__).resolve().parents[3]
    migration_path = (
        root / "apps" / "api" / "migrations" / "versions" / "016_create_usage_events.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    compile(source, str(migration_path), "exec")
