from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CUTOVER = _ROOT / "docs" / "CUTOVER.md"
_COMPOSE = _ROOT / "docker-compose.yml"


def _text() -> str:
    return _CUTOVER.read_text(encoding="utf-8")


def _section(heading: str) -> str:
    text = _text()
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing CUTOVER section: {heading}"
    return match.group("body")


def test_remote_provider_path_starts_one_dedicated_scheduler() -> None:
    remote = _section("Remote-provider cutover (default)")
    start = re.search(r"docker compose up -d (?P<services>[^\n]+)", remote)
    assert start is not None, "remote cutover must explicitly start application services"
    services = shlex.split(start.group("services"))
    assert services == ["api", "worker", "beat", "studio-web"]
    assert " -B" not in remote
    assert "--beat" not in remote


def test_remote_provider_path_has_the_authenticated_cutover_order() -> None:
    remote = _section("Remote-provider cutover (default)")
    ordered_steps = (
        "### 1. Migrate the database",
        "### 2. Bootstrap or configure authentication",
        "### 3. Start the application and Studio proxy",
        "### 4. Run authenticated smoke checks",
    )
    positions = [remote.index(step) for step in ordered_steps]
    assert positions == sorted(positions)
    assert "../README.md#35-bootstrap-an-api-key-first-time-only" in remote


def test_verification_layers_are_separate() -> None:
    verification = _section("Verification ladder")
    headings = re.findall(r"^### (.+)$", verification, re.MULTILINE)
    assert headings == [
        "Liveness",
        "Readiness",
        "Worker registration",
        "Scheduler execution",
        "First MP4",
    ]


def test_remote_and_optional_gpu_paths_are_separate() -> None:
    remote = _section("Remote-provider cutover (default)")
    gpu = _section("Optional local GPU path")
    assert "--profile gpu" not in remote
    assert "--profile gpu" in gpu


def test_success_claims_and_authentication_models_are_explicit() -> None:
    remote = _section("Remote-provider cutover (default)")
    auth = _section("Authentication prerequisites by deployment model")
    assert "offline demo" in remote.lower()
    assert "real provider" in remote.lower()
    assert "Local-only" in auth
    assert "Trusted team" in auth
    assert "Per-user hosted" in auth


def test_every_named_compose_service_exists() -> None:
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    declared = set(compose["services"])
    named: set[str] = set()
    for command in re.findall(r"^docker compose (?P<command>.+)$", _text(), re.MULTILINE):
        tokens = shlex.split(command, comments=True)
        action_index = next(
            (index for index, token in enumerate(tokens) if token in {"build", "exec", "logs", "ps", "pull", "run", "up"}),
            None,
        )
        if action_index is None:
            continue
        action = tokens[action_index]
        candidates = [token for token in tokens[action_index + 1 :] if not token.startswith("-")]
        if action in {"exec", "logs", "run"}:
            named.add(candidates[0])
        else:
            named.update(candidates)
    assert named
    assert named <= declared


def test_relative_links_resolve() -> None:
    for target in re.findall(r"\]\((?!https?://|#)([^)#]+)", _text()):
        assert (_CUTOVER.parent / target).resolve().exists(), f"broken doc link: {target}"
