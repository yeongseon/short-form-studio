"""SF-72: first-run Setup Wizard state machine.

The wizard is a PURE, facts-derived state machine: given the current environment
facts (which model categories are satisfied by a configured+healthy provider, which
configured providers are unhealthy, and whether a first draft exists), it computes
the wizard step, status, and actionable guidance. Because the state is derived from
facts (never a persisted cursor), it is inherently RESUMABLE — re-evaluating after a
restart resumes at the right step. A first draft only needs a healthy LLM (so the
timeline is never empty from a script); IMAGE/TTS/STT are recommended for a full
render but do NOT block the first draft. Guidance names env vars, never key VALUES,
so no credential is ever disclosed.
"""

from __future__ import annotations

import dataclasses

import pytest
from creator_service.setup_wizard import (
    ModelCategory,
    SetupState,
    SetupStatus,
    SetupStep,
    evaluate_setup_state,
    resolve_setup_state,
)

_ALL = {ModelCategory.LLM, ModelCategory.IMAGE, ModelCategory.TTS, ModelCategory.STT}


def _evaluate(
    *,
    satisfied: set[ModelCategory],
    configured: tuple[str, ...] = (),
    configured_categories: set[ModelCategory] | None = None,
    unhealthy: tuple[str, ...] = (),
    has_first_draft: bool = False,
) -> SetupState:
    # Default: a satisfied category was necessarily configured; an unhealthy LLM
    # test overrides this to express "configured but not satisfied".
    resolved_configured_categories = (
        satisfied if configured_categories is None else configured_categories
    )
    return evaluate_setup_state(
        satisfied_categories=frozenset(satisfied),
        configured_categories=frozenset(resolved_configured_categories),
        configured_providers=configured,
        unhealthy_providers=unhealthy,
        has_first_draft=has_first_draft,
    )


# ------------------------- 1. no providers configured -------------------------


def test_no_providers_configured_blocks_at_provider_config() -> None:
    state = _evaluate(satisfied=set())
    assert state.step is SetupStep.PROVIDER_CONFIG
    assert state.status is SetupStatus.BLOCKED
    assert ModelCategory.LLM in state.missing_required_categories
    assert state.can_generate_first_draft is False
    # guidance names an env var, never a value
    assert any(g.env_var == "OPENAI_API_KEY" for g in state.env_var_guidance)


# ------------------------- 2. configured but no LLM capability -------------------------


def test_image_only_still_blocks_the_first_draft_on_missing_llm() -> None:
    state = _evaluate(satisfied={ModelCategory.IMAGE}, configured=("stability",))
    assert state.step is SetupStep.PROVIDER_CONFIG
    assert state.status is SetupStatus.BLOCKED
    assert ModelCategory.LLM in state.missing_required_categories
    assert state.can_generate_first_draft is False


# ------------------------- 3. LLM configured but unhealthy -------------------------


def test_llm_configured_but_unhealthy_blocks_at_required_checks() -> None:
    # The LLM provider is configured (key present) but not satisfied (unreachable),
    # so the wizard reports a useful failure at the checks step, not a crash.
    state = _evaluate(
        satisfied=set(),
        configured=("openai",),
        configured_categories={ModelCategory.LLM},
        unhealthy=("openai",),
    )
    assert state.step is SetupStep.REQUIRED_CHECKS
    assert state.status is SetupStatus.BLOCKED
    assert "openai" in state.unhealthy_providers
    assert any("openai" in f.message for f in state.failures)
    assert state.can_generate_first_draft is False


def test_unrelated_unhealthy_provider_stays_at_provider_config() -> None:
    # Only an IMAGE provider is configured (and unhealthy); the required LLM was
    # never configured, so restoring the image provider cannot pass the required
    # check — the wizard must stay at PROVIDER_CONFIG, surfacing BOTH facts.
    state = _evaluate(
        satisfied=set(),
        configured=("stability",),
        configured_categories={ModelCategory.IMAGE},
        unhealthy=("stability",),
    )
    assert state.step is SetupStep.PROVIDER_CONFIG
    assert state.status is SetupStatus.BLOCKED
    assert ModelCategory.LLM in state.missing_required_categories
    assert "stability" in state.unhealthy_providers


# ------------------------- 4. LLM healthy, no draft -> first-draft ready -------------------------


def test_healthy_llm_without_a_draft_is_first_draft_ready() -> None:
    state = _evaluate(satisfied={ModelCategory.LLM}, configured=("openai",))
    assert state.step is SetupStep.FIRST_DRAFT
    assert state.status is SetupStatus.READY
    assert state.can_generate_first_draft is True
    assert state.full_render_ready is False
    assert {ModelCategory.IMAGE, ModelCategory.TTS, ModelCategory.STT} <= state.missing_recommended_categories


# ------------------------- 5. LLM healthy + recommended missing, non-blocking -------------------------


def test_missing_recommended_categories_do_not_block_the_first_draft() -> None:
    state = _evaluate(satisfied={ModelCategory.LLM})
    assert state.can_generate_first_draft is True
    assert state.missing_required_categories == frozenset()


# ------------------------- 6. LLM healthy + first draft -> complete -------------------------


def test_healthy_llm_with_a_first_draft_is_complete() -> None:
    state = _evaluate(satisfied={ModelCategory.LLM}, configured=("openai",), has_first_draft=True)
    assert state.step is SetupStep.COMPLETE
    assert state.status is SetupStatus.COMPLETE
    assert state.full_render_ready is False  # image/tts/stt still missing


# ------------------------- 7. all categories + draft -> full render ready -------------------------


def test_all_categories_with_a_draft_is_complete_and_full_render_ready() -> None:
    state = _evaluate(satisfied=_ALL, configured=("openai", "groq"), has_first_draft=True)
    assert state.step is SetupStep.COMPLETE
    assert state.full_render_ready is True
    assert state.failures == ()
    assert state.missing_recommended_categories == frozenset()


# ------------------------- 8. resumability / determinism -------------------------


def test_same_facts_produce_equal_state() -> None:
    a = _evaluate(satisfied={ModelCategory.LLM}, configured=("openai",))
    b = _evaluate(satisfied={ModelCategory.LLM}, configured=("openai",))
    assert a == b


def test_only_gaining_a_draft_advances_from_first_draft_to_complete() -> None:
    before = _evaluate(satisfied={ModelCategory.LLM}, configured=("openai",), has_first_draft=False)
    after = _evaluate(satisfied={ModelCategory.LLM}, configured=("openai",), has_first_draft=True)
    assert before.step is SetupStep.FIRST_DRAFT
    assert after.step is SetupStep.COMPLETE


# ------------------------- 9. unavailable provider does not crash -------------------------


def test_unhealthy_provider_yields_a_structured_failure_not_an_exception() -> None:
    state = _evaluate(satisfied=set(), configured=("openai",), unhealthy=("openai",))
    assert state.failures
    assert state.next_action
    assert isinstance(state, SetupState)


# ------------------------- 10. safe defaults -------------------------


def test_safe_defaults_suggest_the_cpu_remote_path_when_nothing_configured() -> None:
    state = _evaluate(satisfied=set())
    assert state.safe_defaults.llm_provider == "openai"
    assert state.safe_defaults.stt_provider == "groq"


# ------------------------- 11. unknown/extra provider ignored -------------------------


def test_unknown_configured_provider_does_not_satisfy_a_category_or_crash() -> None:
    # An unknown provider name that satisfies no category must not falsely unblock
    # the first draft; only real category satisfaction advances the wizard.
    state = _evaluate(satisfied=set(), configured=("myster_provider",))
    assert state.can_generate_first_draft is False
    assert state.step is SetupStep.PROVIDER_CONFIG


# ------------------------- 12. credential non-disclosure (resolver, real env) -------------------------


class _FakeCatalog:
    def __init__(self, satisfied: set[ModelCategory], unhealthy: tuple[str, ...]) -> None:
        self._satisfied = satisfied
        self._unhealthy = unhealthy

    async def category_status(self) -> dict[ModelCategory, tuple[str, ...]]:
        return {c: ("openai",) for c in self._satisfied}

    async def unhealthy_provider_names(self) -> tuple[str, ...]:
        return self._unhealthy


@pytest.mark.asyncio
async def test_resolver_never_discloses_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-test-SECRET-DO-NOT-LEAK-1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", secret)

    state = await resolve_setup_state(
        configured_providers_source=lambda: ["openai"],
        category_status_source=lambda: _FakeCatalog({ModelCategory.LLM}, ()).category_status(),
        unhealthy_source=lambda: _FakeCatalog({ModelCategory.LLM}, ()).unhealthy_provider_names(),
        has_first_draft=False,
    )

    blob = repr(state) + str(dataclasses.asdict(state))
    assert secret not in blob
    assert "SECRET-DO-NOT-LEAK" not in blob
    # safe names ARE present
    assert "openai" in blob
    assert "OPENAI_API_KEY" in blob


@pytest.mark.asyncio
async def test_resolver_resolves_the_ready_state_from_injected_sources() -> None:
    state = await resolve_setup_state(
        configured_providers_source=lambda: ["openai"],
        category_status_source=lambda: _FakeCatalog({ModelCategory.LLM}, ()).category_status(),
        unhealthy_source=lambda: _FakeCatalog({ModelCategory.LLM}, ()).unhealthy_provider_names(),
        has_first_draft=False,
    )
    assert state.step is SetupStep.FIRST_DRAFT
    assert state.can_generate_first_draft is True
