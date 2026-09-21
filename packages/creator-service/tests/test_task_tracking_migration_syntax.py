from pathlib import Path


def test_migration_file_compiles() -> None:
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "apps"
        / "api"
        / "migrations"
        / "versions"
        / "026_create_run_tasks.py"
    )
    source = migration_path.read_text(encoding="utf-8")
    compile(source, str(migration_path), "exec")
