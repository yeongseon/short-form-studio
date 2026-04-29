import asyncio

from creator_service.user_service import InMemoryUserStorage, UserService


def run(coro):
    return asyncio.run(coro)


def test_create_or_get_user_creates_new_user() -> None:
    service = UserService(InMemoryUserStorage())

    user = run(service.create_or_get_user(email="owner@example.com", name="Owner"))

    assert user.id == 1
    assert user.email == "owner@example.com"
    assert user.name == "Owner"
    assert user.auth_provider == "api_key"


def test_create_or_get_user_returns_existing_user_by_email() -> None:
    service = UserService(InMemoryUserStorage())

    first = run(service.create_or_get_user(email="owner@example.com", name="Owner"))
    second = run(service.create_or_get_user(email="owner@example.com", name="Updated"))

    assert second.id == first.id
    assert second.name == "Owner"


def test_get_user_returns_none_for_missing_user() -> None:
    service = UserService(InMemoryUserStorage())

    assert run(service.get_user(999)) is None
