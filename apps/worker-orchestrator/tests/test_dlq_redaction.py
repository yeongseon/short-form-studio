"""P1-5 (V5): the DLQ sanitizer must scrub secret-shaped substrings in string
values, not only redact by dict key name. A ProviderError repr embedding a URL
and a token must never reach Redis / the fallback file in the clear."""

import celery_app


def test_sanitize_redacts_secret_shaped_substrings_in_string_values() -> None:
    leaky = "https://api.openai.com/v1: 401 token=sk-abcdef1234567890abcdef"
    sanitized = celery_app._sanitize_for_dlq({"exception": f"ProviderAuthError({leaky!r})"})
    blob = str(sanitized)
    assert "sk-abcdef1234567890abcdef" not in blob
    assert "api.openai.com" not in blob
    assert "https://" not in blob


def test_sanitize_redacts_nested_and_list_string_values() -> None:
    sanitized = celery_app._sanitize_for_dlq(
        {
            "args": ["/home/user/app/render.py failed", "ghp_abcdef1234567890ABCDEFghij"],
            "meta": {"note": "wrote /workspaces/1/assets/secret.png"},
        }
    )
    blob = str(sanitized)
    assert "/home/user" not in blob
    assert "ghp_abcdef1234567890ABCDEFghij" not in blob
    assert "/workspaces/1/assets" not in blob


def test_sanitize_preserves_safe_strings() -> None:
    sanitized = celery_app._sanitize_for_dlq({"task_name": "generate_script", "run_id": 42})
    assert isinstance(sanitized, dict)
    assert sanitized["task_name"] == "generate_script"
    assert sanitized["run_id"] == 42


def test_sanitize_still_redacts_sensitive_key_names() -> None:
    sanitized = celery_app._sanitize_for_dlq({"api_key": "whatever", "token": "xyz"})
    assert isinstance(sanitized, dict)
    assert sanitized["api_key"] == "<redacted>"
    assert sanitized["token"] == "<redacted>"
