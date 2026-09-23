"""Exercise the dependency gate through its real CLI, without importing application code."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_package_dependencies.py"
PACKAGES = ("creator_domain", "creator_service", "creator_provider")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    for package in PACKAGES:
        source = tmp_path / "packages" / package.replace("_", "-") / package
        source.mkdir(parents=True)
        (source / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def run_gate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)],
        cwd=root.parent,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_fails_with_location_when_lateral_dependency_exists(repository: Path) -> None:
    # Given a forbidden import in production source.
    path = "packages/creator-service/creator_service/bad.py"
    (repository / path).write_text("import creator_provider as provider\n", encoding="utf-8")
    # When the CLI scans a repository from another working directory.
    result = run_gate(repository)
    # Then it fails with the offending edge and source location.
    assert result.returncode == 1
    assert f"{path}:1:" in result.stdout
    assert "creator_service -> creator_provider" in result.stdout


def test_passes_when_only_downward_and_test_dependencies_exist(repository: Path) -> None:
    # Given allowed production imports, comments, and forbidden test-only imports.
    service = repository / "packages/creator-service"
    (service / "creator_service/good.py").write_text(
        'from creator_domain import models\n# import tasks\ntext = "import shorts_api"\n',
        encoding="utf-8",
    )
    (service / "tests").mkdir()
    (service / "tests/test_example.py").write_text("import creator_provider\n", encoding="utf-8")
    # When the production gate runs.
    result = run_gate(repository)
    # Then test fixtures do not create false violations.
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "content", ["def broken(:\n", "import importlib\nimportlib.import_module(name)\n"]
)
def test_fails_closed_when_source_cannot_be_checked(repository: Path, content: str) -> None:
    # Given syntax that cannot be parsed or a computed dependency that cannot be resolved.
    path = "packages/creator-domain/creator_domain/unknown.py"
    (repository / path).write_text(content, encoding="utf-8")
    # When the gate runs.
    result = run_gate(repository)
    # Then it reports the source instead of claiming compliance.
    assert result.returncode == 1
    assert path in result.stdout


def test_fails_when_source_root_is_missing(tmp_path: Path) -> None:
    # Given a wrong or incomplete checkout.
    # When the gate runs.
    result = run_gate(tmp_path)
    # Then it cannot pass vacuously.
    assert result.returncode == 1
    assert "creator-domain" in result.stdout


def test_reports_all_violations_when_multiple_files_fail(repository: Path) -> None:
    # Given independent violations, including a worker module outside tasks.
    domain = repository / "packages/creator-domain/creator_domain"
    (domain / "a.py").write_text("import creator_service\n", encoding="utf-8")
    (domain / "z.py").write_text('__import__("celery_app")\n', encoding="utf-8")
    # When the gate runs.
    result = run_gate(repository)
    # Then both edges are actionable in deterministic path order.
    assert result.returncode == 1
    assert result.stdout.index("a.py:1:") < result.stdout.index("z.py:1:")
    assert "creator_domain -> celery_app" in result.stdout
