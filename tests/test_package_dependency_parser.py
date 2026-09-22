from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("module", "source", "targets"),
    [
        ("creator_service.example", "import creator_provider as p", ["creator_provider"]),
        (
            "creator_service.example",
            "import os, creator_provider.registry as r",
            ["creator_provider.registry"],
        ),
        (
            "creator_provider.example",
            "from creator_service import storage as s",
            ["creator_service"],
        ),
        (
            "creator_domain.example",
            "from creator_service.storage import (Store as S,)",
            ["creator_service.storage"],
        ),
        ("creator_domain.example", "import creator_provider", ["creator_provider"]),
        ("creator_domain.example", "from shorts_api.auth import User", ["shorts_api.auth"]),
        ("creator_provider.example", "import tasks.render_video as render", ["tasks.render_video"]),
        ("creator_service.example", "from apps.api.src import shorts_api as api", ["apps.api.src"]),
        ("creator_service.example", "import worker_loop", ["worker_loop"]),
        (
            "creator_service.example",
            "if TYPE_CHECKING:\n    import creator_provider",
            ["creator_provider"],
        ),
        (
            "creator_service.example",
            "def lazy():\n    import creator_provider",
            ["creator_provider"],
        ),
        ("creator_service.example", "from creator_domain import models", []),
        ("creator_provider.example", "from creator_domain.models import Scene", []),
        ("creator_service.example", "from . import storage", []),
        ("creator_service.sub.example", "from ..storage import Store", []),
        ("creator_domain.example", "from . import shorts_api", []),
        (
            "creator_domain.example",
            '"""from creator_service import X"""\n# import tasks\nx = "import creator_provider"',
            [],
        ),
        ("creator_domain.example", "import creator_service_extra, tasks_extra", []),
        (
            "creator_service.example",
            'import importlib\nimportlib.import_module("creator_provider.registry")',
            ["creator_provider.registry"],
        ),
        (
            "creator_provider.example",
            'import importlib as il\nil.import_module(name="tasks.render_video")',
            ["tasks.render_video"],
        ),
        (
            "creator_service.example",
            'from importlib import import_module as load\nload("shorts_api.auth")',
            ["shorts_api.auth"],
        ),
        (
            "creator_service.example",
            'from importlib import import_module\nimport_module(".registry", "creator_provider")',
            ["creator_provider.registry"],
        ),
        (
            "creator_domain.example",
            'from importlib import import_module as load\nload(".auth", package="shorts_api")',
            ["shorts_api.auth"],
        ),
        (
            "creator_service.example",
            'from importlib import import_module\nimport_module(".storage", __package__)',
            [],
        ),
        ("creator_domain.example", '__import__("celery_app")', ["celery_app"]),
        (
            "creator_domain.example",
            'from builtins import __import__ as load\nload("tasks")',
            ["tasks"],
        ),
        (
            "creator_domain.example",
            'import builtins as b\nb.__import__("shorts_api")',
            ["shorts_api"],
        ),
        ("creator_domain.example", 'import importlib\nimportlib.import_module("json")', []),
        (
            "creator_service.example",
            'import importlib\nimportlib.import_module("creator_domain.models")',
            [],
        ),
        (
            "creator_domain.example",
            'def import_module(name): return name\nimport_module("tasks")',
            [],
        ),
        (
            "creator_service.example",
            'from importlib import import_module as load\nload("tasks")\ndef unrelated():\n    from json import loads as load',
            ["tasks"],
        ),
        (
            "creator_service.example",
            'import importlib as loader\nloader.import_module("tasks")\ndef unrelated():\n    import json as loader',
            ["tasks"],
        ),
    ],
)
def test_reports_only_forbidden_edges_when_parsing_imports(
    module: str,
    source: str,
    targets: list[str],
) -> None:
    # Given source text and its canonical Python module name.
    from scripts.check_package_dependencies import check_source

    # When Python's AST is checked against ADR001.
    issues = check_source(source, module)
    # Then import syntax, not incidental text, determines dependency edges.
    assert [issue.target for issue in issues] == targets


@pytest.mark.parametrize(
    "source",
    [
        "from ..shorts_api import auth",
        "from ... import tasks",
        "from importlib import import_module\nimport_module(module_name)",
        'import importlib\nimportlib.import_module(".auth", package=package_name)',
        "__import__(name)",
        'import importlib\nimportlib.import_module(f"tasks.{stage}")',
        '__import__("auth", level=1)',
    ],
)
def test_reports_unresolved_import_when_resolution_is_impossible(source: str) -> None:
    # Given a computed or invalid relative import, which must not disappear from the audit.
    from scripts.check_package_dependencies import check_source

    # When the parser attempts static resolution.
    issues = check_source(source, "creator_service.example")
    # Then a blocking diagnostic identifies the unresolved dependency.
    assert len(issues) == 1
    assert issues[0].reason == "unresolved-import"


def test_resolves_relative_import_when_source_is_package_initializer() -> None:
    # Given __init__.py, whose relative base is itself rather than its parent.
    from scripts.check_package_dependencies import check_source

    # When a sibling module is imported.
    issues = check_source("from .storage import Store", "creator_service", True)
    # Then the self-package dependency is allowed.
    assert issues == ()


@pytest.mark.parametrize("owner", ["creator_domain", "creator_service", "creator_provider"])
@pytest.mark.parametrize("target", ["creator_domain", "creator_service", "creator_provider"])
def test_enforces_dependency_matrix_when_importing_internal_package(
    owner: str, target: str
) -> None:
    # Given every internal source/target combination in ADR001.
    from scripts.check_package_dependencies import check_source

    allowed = owner == target or target == "creator_domain"
    # When an internal package is imported.
    issues = check_source(f"import {target}", f"{owner}.example")
    # Then only self-package and downward-to-domain edges pass.
    assert bool(issues) is not allowed
