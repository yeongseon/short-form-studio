import pytest
from creator_service.onboarding import build_onboarding_guidance
from creator_service.setup_wizard import ModelCategory, evaluate_setup_state


@pytest.mark.parametrize("has_draft", [False, True])
@pytest.mark.parametrize("provider_ready", [False, True])
def test_returning_workspace_exposes_actual_setup_progress(
    has_draft: bool, provider_ready: bool,
) -> None:
    # Given a returning workspace whose provider and draft facts vary independently.
    categories = frozenset({ModelCategory.LLM}) if provider_ready else frozenset()
    setup = evaluate_setup_state(
        satisfied_categories=categories, configured_categories=categories,
        configured_providers=(), unhealthy_providers=(), has_first_draft=has_draft,
    )
    # When onboarding guidance is built.
    guidance = build_onboarding_guidance(setup_state=setup, has_existing_projects=True)
    # Then the setup cursor and milestone are not replaced by project existence.
    assert guidance.setup_step == setup.step
    assert guidance.setup_status == setup.status
    assert guidance.has_first_draft is has_draft
    assert guidance.next_action == setup.next_action
