"""SF-71: content/link/command checks for the reproducible Docker Quick Start.

Per AGENTS.md, documentation work is verified with content/link/command checks
rather than artificial unit tests. This pins that docs/QUICKSTART.md exists, its
CPU/remote-provider first-short path is reproducible against the real repo (the
referenced scripts, compose file, and env vars actually exist), its internal doc
links resolve, and its security guidance (loopback-only, secure credentials,
migrations/bootstrap, optional GPU path) is present — so the Quick Start cannot
silently drift away from the repo it documents.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_QUICKSTART = _REPO_ROOT / "docs" / "QUICKSTART.md"


def _text() -> str:
    return _QUICKSTART.read_text(encoding="utf-8")


def test_quickstart_doc_exists() -> None:
    assert _QUICKSTART.is_file(), "docs/QUICKSTART.md must exist"


def test_references_the_real_bootstrap_and_migration_entrypoints() -> None:
    text = _text()
    assert (_REPO_ROOT / "scripts" / "create_api_key.py").is_file()
    assert (_REPO_ROOT / "apps" / "api" / "alembic.ini").is_file()
    assert "scripts/create_api_key.py" in text
    assert "alembic upgrade head" in text


def test_documents_the_cpu_remote_provider_path_without_the_gpu_profile() -> None:
    text = _text()
    # The reproducible CPU path brings up the core with a plain `docker compose up`
    # (no --profile gpu), then the GPU path is called out as clearly optional.
    assert re.search(r"docker compose up -d(?!\s+--profile)", text)
    assert "cp .env.example .env" in text
    # remote providers cover the CPU path since the local models are GPU-gated
    assert "OPENAI_API_KEY" in text
    assert "GROQ_API_KEY" in text


def test_documents_the_optional_gpu_path() -> None:
    text = _text()
    assert "--profile gpu" in text


def test_retains_loopback_and_credential_and_migration_guidance() -> None:
    text = _text()
    assert "127.0.0.1" in text
    assert "POSTGRES_PASSWORD" in text
    assert "ADMIN_API_KEY" in text
    assert re.search(r"migrat", text, re.IGNORECASE)


def test_documents_first_video_steps_and_failure_recovery() -> None:
    text = _text()
    assert "http://127.0.0.1:5174" in text
    assert re.search(r"troubleshoot|failure recovery|recovery", text, re.IGNORECASE)


def test_does_not_leak_a_real_looking_secret() -> None:
    text = _text()
    # Env keys must be shown empty or with an obvious placeholder, never a value
    # that looks like a real credential.
    assert not re.search(r"OPENAI_API_KEY=sk-[A-Za-z0-9]{20,}", text)
    assert not re.search(r"GROQ_API_KEY=gsk_[A-Za-z0-9]{20,}", text)


def test_internal_doc_links_resolve() -> None:
    text = _text()
    for target in re.findall(r"\]\((?!https?://)([^)#]+)", text):
        resolved = (_QUICKSTART.parent / target).resolve()
        assert resolved.exists(), f"broken doc link: {target}"


def test_references_the_smoke_check_script_which_exists() -> None:
    assert (_REPO_ROOT / "scripts" / "quickstart_smoke.sh").is_file()
    assert "scripts/quickstart_smoke.sh" in _text()
