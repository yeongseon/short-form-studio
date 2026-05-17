"""Verify _sync_runner_dependencies is completely removed from all task modules.

PR 8: Worker dependency injection cleanup — the monkey-patching pattern
where each task file re-assigned task_runner module globals is now removed.
task_runner.py owns its own imports; tests patch task_runner directly.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
from types import ModuleType

import pytest

TASKS_DIR = pathlib.Path(__file__).resolve().parent.parent / "tasks"

# All task modules that previously had _sync_runner_dependencies
TASK_MODULE_NAMES = [
    "tasks.generate_script",
    "tasks.generate_audio",
    "tasks.generate_scene_image",
    "tasks.generate_visual_plan",
    "tasks.generate_subtitles",
    "tasks.generate_paragraph_audio",
    "tasks.generate_paragraph_subtitles",
    "tasks.render_video",
]


@pytest.mark.parametrize("module_name", TASK_MODULE_NAMES)
def test_no_sync_runner_dependencies_function(module_name: str) -> None:
    """No task module should define _sync_runner_dependencies."""
    mod: ModuleType = importlib.import_module(module_name)
    assert not hasattr(mod, "_sync_runner_dependencies"), (
        f"{module_name} still has _sync_runner_dependencies"
    )


@pytest.mark.parametrize("module_name", TASK_MODULE_NAMES)
def test_no_task_runner_module_import(module_name: str) -> None:
    """No task module should import task_runner as _task_runner for monkey-patching."""
    # Parse the source to check for `from tasks import task_runner as _task_runner`
    short_name = module_name.split(".")[-1]
    source_file = TASKS_DIR / f"{short_name}.py"
    tree = ast.parse(source_file.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tasks":
            for alias in node.names:
                if alias.name == "task_runner" and alias.asname == "_task_runner":
                    pytest.fail(
                        f"{module_name} still has 'from tasks import task_runner as _task_runner'"
                    )
