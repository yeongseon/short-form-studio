from pathlib import Path


def test_migration_012_python_syntax_is_valid() -> None:
    migration_path = Path("apps/api/migrations/versions/012_create_users_and_workspaces.py")
    source = migration_path.read_text(encoding="utf-8")
    compile(source, str(migration_path), "exec")


def test_migration_013_python_syntax_is_valid() -> None:
    migration_path = Path("apps/api/migrations/versions/013_add_workspace_to_projects_and_runs.py")
    source = migration_path.read_text(encoding="utf-8")
    compile(source, str(migration_path), "exec")
