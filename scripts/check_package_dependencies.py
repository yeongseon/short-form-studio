#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# ─── How to run ───
# uv run scripts/check_package_dependencies.py [repository-root]
# CI (stdlib only): python3 scripts/check_package_dependencies.py
"""AST-only ADR001 gate. Never imports or executes the inspected application code."""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path
from typing import Final

PACKAGES: Final = ("creator_domain", "creator_service", "creator_provider")
APP_ROOTS: Final = frozenset({"apps", "shorts_api", "tasks", "celery_app", "worker_loop"})


@dataclass(frozen=True, slots=True)
class Issue:
    line: int
    target: str
    reason: str


class ImportChecker(ast.NodeVisitor):
    """Accumulate import edges and loader aliases; unknown dynamic targets fail closed.

    Alias collection is deliberately conservative across scopes: a shadowed loader
    can produce a diagnostic, but shadowing cannot hide a recognized import call.
    """

    def __init__(self, module: str, package: str) -> None:
        self.owner = module.split(".")[0]
        self.package = package
        self.aliases: dict[str, set[str]] = {"__import__": {"builtins.__import__"}}
        self.edges: list[tuple[int, str]] = []
        self.issues: list[Issue] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.edges.append((node.lineno, alias.name))
            self.aliases.setdefault(alias.asname or alias.name.split(".")[0], set()).add(
                alias.name if alias.asname else alias.name.split(".")[0]
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        try:
            module = resolve_name("." * node.level + (node.module or ""), self.package)
        except (ImportError, ValueError):
            self.issues.append(
                Issue(node.lineno, "." * node.level + (node.module or ""), "unresolved-import")
            )
            return
        self.edges.append((node.lineno, module))
        for alias in node.names:
            self.aliases.setdefault(alias.asname or alias.name, set()).add(f"{module}.{alias.name}")
            if node.module is None:
                self.edges.append((node.lineno, f"{module}.{alias.name}"))

    def qualified_names(self, node: ast.expr) -> set[str]:
        # AST is an open hierarchy; unrelated expressions are intentionally unmatched.
        match node:
            case ast.Name(id=name):
                return self.aliases.get(name, {name})
            case ast.Attribute(value=value, attr=attr):
                return {f"{name}.{attr}" for name in self.qualified_names(value)}
        return set()

    def literal(self, node: ast.expr | None) -> str | None:
        match node:
            case ast.Constant(value=str() as value):
                return value
            case ast.Name(id="__package__"):
                return self.package
        return None

    def visit_Call(self, node: ast.Call) -> None:
        loaders = self.qualified_names(node.func) & {
            "importlib.import_module",
            "builtins.__import__",
        }
        for loader in sorted(loaders):
            keywords = {keyword.arg: keyword.value for keyword in node.keywords}
            name = self.literal(node.args[0] if node.args else keywords.get("name"))
            package = self.literal(node.args[1] if len(node.args) > 1 else keywords.get("package"))
            level = node.args[4] if len(node.args) > 4 else keywords.get("level")
            if (
                loader == "builtins.__import__"
                and level is not None
                and ast.dump(level) != "Constant(value=0)"
            ):
                name = None
            try:
                target = resolve_name(name, package) if name else None
            except (ImportError, ValueError):
                target = None
            if target is None:
                self.issues.append(Issue(node.lineno, ast.unparse(node), "unresolved-import"))
            else:
                self.edges.append((node.lineno, target))


def check_source(source: str | bytes, module: str, is_package: bool = False) -> tuple[Issue, ...]:
    """Return forbidden/unresolved imports, retaining exact targets and line numbers."""
    tree = ast.parse(source)
    checker = ImportChecker(module, module if is_package else module.rpartition(".")[0])
    # Bind direct import aliases before checking calls, including calls in lazy bodies.
    for node in ast.walk(tree):
        match node:
            case ast.Import():
                checker.visit_Import(node)
            case ast.ImportFrom():
                checker.visit_ImportFrom(node)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Calls are already traversed by ast.walk; do not visit nested calls twice.
            checker.visit_Call(node)
    allowed = {checker.owner}
    if checker.owner != "creator_domain":
        allowed.add("creator_domain")
    for line, target in checker.edges:
        root = target.split(".")[0]
        if root in (set(PACKAGES) | APP_ROOTS) - allowed:
            checker.issues.append(Issue(line, target, "forbidden-dependency"))
    return tuple(sorted(set(checker.issues), key=lambda issue: (issue.line, issue.target)))


def check_repository(root: Path) -> tuple[str, ...]:
    """Scan only production package roots; missing roots and invalid syntax are errors."""
    diagnostics: list[str] = []
    for package in PACKAGES:
        source_root = root / "packages" / package.replace("_", "-") / package
        files = sorted(source_root.rglob("*.py"))
        if not files:
            diagnostics.append(
                f"{source_root.relative_to(root)}: missing or empty production source root"
            )
        for path in files:
            relative = path.relative_to(source_root).with_suffix("")
            is_package = path.name == "__init__.py"
            parts = relative.parts[:-1] if is_package else relative.parts
            module = ".".join((package, *parts))
            try:
                issues = check_source(path.read_bytes(), module, is_package)
            except (SyntaxError, UnicodeError, OSError) as error:
                diagnostics.append(f"{path.relative_to(root)}: cannot check source: {error}")
                continue
            diagnostics.extend(
                f"{path.relative_to(root)}:{issue.line}: {issue.reason}: {package} -> {issue.target}"
                for issue in issues
            )
    return tuple(diagnostics)


def main() -> int:
    if len(sys.argv) > 2 or any(arg.startswith("-") for arg in sys.argv[1:]):
        print("Usage: python3 scripts/check_package_dependencies.py [repository-root]")
        return 2
    root = (
        Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else Path(__file__).resolve().parents[1]
    )
    diagnostics = check_repository(root)
    for diagnostic in diagnostics:
        print(diagnostic)
    print(f"ADR001: {len(diagnostics)} blocking diagnostic(s); no baseline or exemptions.")
    return int(bool(diagnostics))


if __name__ == "__main__":
    raise SystemExit(main())
