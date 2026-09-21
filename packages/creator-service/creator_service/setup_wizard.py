"""SF-72: first-run Setup Wizard state machine.

The wizard is a PURE, facts-derived state machine: given the current environment
facts (which model categories are satisfied by a configured+healthy provider, which
configured providers are unhealthy, and whether a first draft exists), it computes
the wizard step, status, and actionable guidance. Because the state is derived from
facts (never a persisted cursor), it is inherently RESUMABLE — re-evaluating after a
restart resumes at the right step. A first draft only needs a healthy LLM (so the
timeline is never empty from a script); IMAGE/TTS/STT are recommended for a full
render but do NOT block the first draft. Guidance names env vars, never key VALUES,
so no credential is ever disclosed: the state carries only provider names, category
readiness, env-var-name guidance, and booleans.
"""

from __future__ import annotations

import enum
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


class ModelCategory(enum.Enum):
    LLM = "llm"
    IMAGE = "image"
    TTS = "tts"
    STT = "stt"


class SetupStep(enum.Enum):
    PROVIDER_CONFIG = "provider_config"
    REQUIRED_CHECKS = "required_checks"
    FIRST_DRAFT = "first_draft"
    COMPLETE = "complete"


class SetupStatus(enum.Enum):
    BLOCKED = "blocked"
    READY = "ready"
    COMPLETE = "complete"


# A first draft (non-empty timeline) needs a script, so LLM is the only REQUIRED
# capability; the rest are recommended for a full render but never block the draft.
_REQUIRED = frozenset({ModelCategory.LLM})
_RECOMMENDED = frozenset({ModelCategory.IMAGE, ModelCategory.TTS, ModelCategory.STT})

# Category -> the safe default env var whose provider can satisfy it (SF-71 CPU path:
# OpenAI for LLM/IMAGE/TTS, Groq for remote STT). Names only, never values.
_DEFAULT_ENV_VAR: dict[ModelCategory, tuple[str, str]] = {
    ModelCategory.LLM: ("openai", "OPENAI_API_KEY"),
    ModelCategory.IMAGE: ("openai", "OPENAI_API_KEY"),
    ModelCategory.TTS: ("openai", "OPENAI_API_KEY"),
    ModelCategory.STT: ("groq", "GROQ_API_KEY"),
}


@dataclass(frozen=True)
class EnvVarGuidance:
    provider: str
    category: ModelCategory
    env_var: str


@dataclass(frozen=True)
class SetupFailure:
    code: str
    message: str


@dataclass(frozen=True)
class SetupDefaults:
    llm_provider: str = "openai"
    image_provider: str = "openai"
    tts_provider: str = "openai"
    stt_provider: str = "groq"


@dataclass(frozen=True)
class SetupState:
    step: SetupStep
    status: SetupStatus
    satisfied_categories: frozenset[ModelCategory]
    missing_required_categories: frozenset[ModelCategory]
    missing_recommended_categories: frozenset[ModelCategory]
    configured_providers: tuple[str, ...]
    unhealthy_providers: tuple[str, ...]
    env_var_guidance: tuple[EnvVarGuidance, ...]
    safe_defaults: SetupDefaults
    failures: tuple[SetupFailure, ...]
    next_action: str
    can_generate_first_draft: bool
    full_render_ready: bool


def evaluate_setup_state(
    *,
    satisfied_categories: frozenset[ModelCategory],
    configured_categories: frozenset[ModelCategory],
    configured_providers: tuple[str, ...],
    unhealthy_providers: tuple[str, ...],
    has_first_draft: bool,
) -> SetupState:
    """Compute the wizard state from environment facts (pure, credential-free)."""
    missing_required = _REQUIRED - satisfied_categories
    missing_recommended = _RECOMMENDED - satisfied_categories
    can_generate_first_draft = not missing_required
    full_render_ready = not (missing_required | missing_recommended)
    # A required check only fails when the required capability was actually
    # configured but is not satisfied (unreachable). An unrelated unhealthy
    # provider must not move the wizard past provider configuration.
    failed_required_checks = (_REQUIRED & configured_categories) - satisfied_categories

    guidance = tuple(
        EnvVarGuidance(
            provider=_DEFAULT_ENV_VAR[category][0],
            category=category,
            env_var=_DEFAULT_ENV_VAR[category][1],
        )
        for category in ModelCategory
        if category in (missing_required | missing_recommended)
    )

    failures: list[SetupFailure] = []
    for provider in unhealthy_providers:
        failures.append(
            SetupFailure(
                code="provider_unreachable",
                message=f"provider {provider!r} is configured but unreachable",
            )
        )
    for category in sorted(missing_required, key=lambda c: c.value):
        failures.append(
            SetupFailure(
                code="missing_required_capability",
                message=f"no configured provider satisfies the required {category.value} capability",
            )
        )

    step, status, next_action = _resolve_step(
        missing_required=missing_required,
        failed_required_checks=failed_required_checks,
        has_first_draft=has_first_draft,
        full_render_ready=full_render_ready,
    )

    return SetupState(
        step=step,
        status=status,
        satisfied_categories=satisfied_categories,
        missing_required_categories=missing_required,
        missing_recommended_categories=missing_recommended,
        configured_providers=configured_providers,
        unhealthy_providers=unhealthy_providers,
        env_var_guidance=guidance,
        safe_defaults=SetupDefaults(),
        failures=tuple(failures),
        next_action=next_action,
        can_generate_first_draft=can_generate_first_draft,
        full_render_ready=full_render_ready,
    )


def _resolve_step(
    *,
    missing_required: frozenset[ModelCategory],
    failed_required_checks: frozenset[ModelCategory],
    has_first_draft: bool,
    full_render_ready: bool,
) -> tuple[SetupStep, SetupStatus, str]:
    if missing_required:
        # A required capability was configured but is unreachable => the user is
        # past config and stuck on checks; otherwise they still need to configure
        # a provider for the required capability.
        if failed_required_checks:
            return (
                SetupStep.REQUIRED_CHECKS,
                SetupStatus.BLOCKED,
                "restore the unreachable provider(s) so the required checks pass",
            )
        return (
            SetupStep.PROVIDER_CONFIG,
            SetupStatus.BLOCKED,
            "configure a provider for the required LLM capability (e.g. set OPENAI_API_KEY)",
        )
    if not has_first_draft:
        return (
            SetupStep.FIRST_DRAFT,
            SetupStatus.READY,
            "generate a first draft so the timeline is not empty",
        )
    if not full_render_ready:
        return (
            SetupStep.COMPLETE,
            SetupStatus.COMPLETE,
            "setup complete; configure IMAGE/TTS/STT providers for a full render",
        )
    return (SetupStep.COMPLETE, SetupStatus.COMPLETE, "setup complete")


async def resolve_setup_state(
    *,
    configured_providers_source: Callable[[], list[str]],
    category_status_source: Callable[[], Awaitable[dict[ModelCategory, tuple[str, ...]]]],
    unhealthy_source: Callable[[], Awaitable[tuple[str, ...]]],
    has_first_draft: bool,
) -> SetupState:
    """Wire the real credential/health/draft sources into the pure evaluator.

    The sources supply only credential-free facts (provider names, category
    readiness, health), so no key value is ever read into the wizard state.
    """
    configured = tuple(configured_providers_source())
    category_status = await category_status_source()
    unhealthy = await unhealthy_source()
    # A category key is present when a provider was configured for it; a non-empty
    # provider tuple means at least one configured provider is healthy (satisfied).
    configured_categories = frozenset(category_status)
    satisfied = frozenset(
        category for category, providers in category_status.items() if providers
    )
    return evaluate_setup_state(
        satisfied_categories=satisfied,
        configured_categories=configured_categories,
        configured_providers=configured,
        unhealthy_providers=unhealthy,
        has_first_draft=has_first_draft,
    )