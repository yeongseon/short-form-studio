"""SF-79: content/link/command/route/honesty checks for the first-Short walkthrough.

Per AGENTS.md, documentation work is verified with content/link/command checks
rather than artificial unit tests. This pins that docs/FIRST_SHORT_WALKTHROUGH.md
exists, its internal links resolve, it references real setup commands and real API
routes (so it cannot drift from the code it documents), it states prerequisites
honestly, keeps preview/download loopback-only, and — critically — never claims
the under-10-minute KPI is achieved without a recorded measurement.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOC = _REPO_ROOT / "docs" / "FIRST_SHORT_WALKTHROUGH.md"
_ROUTES_DIR = _REPO_ROOT / "apps" / "api" / "src" / "shorts_api" / "routes"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _routes_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in _ROUTES_DIR.glob("*.py")
    )


def test_first_short_walkthrough_doc_exists() -> None:
    assert _DOC.is_file(), "docs/FIRST_SHORT_WALKTHROUGH.md must exist"
    assert _text().strip(), "walkthrough must not be empty"


def test_internal_links_resolve() -> None:
    text = _text()
    for target in re.findall(r"\]\((?!https?://)([^)#]+)", text):
        resolved = (_DOC.parent / target).resolve()
        assert resolved.exists(), f"broken doc link: {target}"


def test_references_canonical_setup() -> None:
    text = _text()
    assert "cp .env.example .env" in text
    assert re.search(r"docker compose up -d", text)
    assert "alembic upgrade head" in text
    assert "scripts/create_api_key.py" in text
    assert "http://127.0.0.1:5174" in text
    assert "QUICKSTART.md" in text
    assert (_REPO_ROOT / "scripts" / "create_api_key.py").is_file()
    assert (_REPO_ROOT / "docs" / "QUICKSTART.md").is_file()


def test_prerequisites_are_honest() -> None:
    lower = _text().lower()
    assert "docker" in lower
    assert "openai_api_key" in lower
    assert "groq_api_key" in lower
    assert "gpu" in lower and "optional" in lower
    assert "cannot proceed" in lower or "blocked" in lower


def test_documented_routes_exist_in_source() -> None:
    source = _routes_source()
    fragments = [
        "/workspaces/{workspace_id}/demo-short/plan",
        "/workspaces/{workspace_id}/demo-short/runs",
        "/{workspace_id}/onboarding",
        "/{project_id}/timeline",
        "/{project_id}/timeline/preview",
        "/runs/{run_id}/generate-audio",
        "/runs/{run_id}/generate-subtitles",
        "/runs/{run_id}/render",
        "/runs/{run_id}/approve-timeline-render",
        "/runs/{run_id}/preview",
        "/runs/{run_id}/artifacts/{artifact_id}/download",
        "/runs/{run_id}/visual-plan/scenes/{scene_id}/generate-image",
    ]
    for fragment in fragments:
        assert fragment in source, f"documented route not found in source: {fragment}"


def test_sample_and_review_gates_not_bypassed() -> None:
    text = _text()
    assert "demo-short" in text
    for gate in ("SCRIPT", "VISUAL_PLAN", "VISUAL_ASSET", "FINAL"):
        assert gate in text, f"review gate not documented: {gate}"
    lower = text.lower()
    assert "not bypass" in lower or "never bypass" in lower


def test_covers_required_user_journey() -> None:
    lower = _text().lower()
    for term in ("install", "set up", "upload", "generate", "review", "preview", "download", "edit"):
        assert term in lower, f"journey step missing: {term}"


def test_loopback_download_guidance() -> None:
    text = _text()
    assert "127.0.0.1" in text
    lower = text.lower()
    assert "loopback" in lower or "local-only" in lower or "local only" in lower
    assert "0.0.0.0" not in text.replace("never bound to `0.0.0.0`", "")


def test_actionable_errors_recovery_referenced() -> None:
    lower = _text().lower()
    assert "recovery" in lower
    assert "retry" in lower
    assert "failure summary" in lower or "actionable" in lower


def test_no_secret_leak() -> None:
    text = _text()
    assert not re.search(r"OPENAI_API_KEY=sk-[A-Za-z0-9]{20,}", text)
    assert not re.search(r"GROQ_API_KEY=gsk_[A-Za-z0-9]{20,}", text)


def test_kpi_honesty() -> None:
    text = _text()
    lower = text.lower()
    # Positive honest framing.
    assert "target" in lower
    assert "not a measured result" in lower or "not measured" in lower
    assert "start" in lower and "end" in lower
    assert "clone" in lower
    assert "preview" in lower or "download" in lower
    # Negative: never affirm the KPI is achieved.
    forbidden = [
        r"\bkpi\s+met\b",
        r"\bkpi\s+achieved\b",
        r"achieved\s+the\s+.*10[- ]minute",
        r"under\s+10\s+minutes\s*[\u2713\u2705]",
        r"[\u2713\u2705]\s*under\s+10\s+minutes",
        r"guaranteed\s+under\s+10\s+minutes",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, lower), f"forbidden KPI claim: {pattern}"


def test_has_recorded_validation_entry() -> None:
    lower = _text().lower()
    # A concrete recorded run (completed or prerequisite-blocked), not an empty template.
    assert "recorded validation runs" in lower
    assert re.search(r"20\d\d-\d\d-\d\d", _text()), "measurement row needs a concrete date"
    assert "kpi not measured" in lower or "not a completed first short" in lower
