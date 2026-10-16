from pathlib import Path

from fastapi.testclient import TestClient

from shorts_api.app_factory import create_app
from shorts_api.auth import CurrentUser, get_current_user
from shorts_api.routes import release_identity
from shorts_api.routes.release_identity import ServiceIdentity, resolve_worker_identity


ROOT = Path(__file__).resolve().parents[3]
SOURCE_SHA = "b" * 40
API_DIGEST = "sha256:" + "a" * 64
WORKER_DIGEST = "sha256:" + "c" * 64


def test_api_release_identity_reports_build_and_database_identity(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_SHA", SOURCE_SHA)
    monkeypatch.setenv("API_IMAGE_DIGEST", API_DIGEST)
    revision_file = ROOT / ".test-alembic-revision"
    revision_file.write_text("035_add_api_keys")
    monkeypatch.setattr(release_identity, "ALEMBIC_REVISION_PATH", revision_file)
    app = create_app()

    async def current_user() -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=1)

    app.dependency_overrides[get_current_user] = current_user

    response = TestClient(app).get("/release/identity")
    revision_file.unlink()

    assert response.status_code == 200
    assert response.json() == {
        "source_sha": SOURCE_SHA,
        "digest": API_DIGEST,
        "alembic_revision": "035_add_api_keys",
    }


def test_worker_release_identity_reports_worker_build(monkeypatch) -> None:
    app = create_app()

    async def stored_worker_identity() -> list[ServiceIdentity]:
        return [ServiceIdentity(source_sha=SOURCE_SHA, digest=WORKER_DIGEST)]

    async def current_user() -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=1)

    app.dependency_overrides[resolve_worker_identity] = stored_worker_identity
    app.dependency_overrides[get_current_user] = current_user

    response = TestClient(app).get("/release/worker-identity")

    assert response.status_code == 200
    assert response.json() == [{"source_sha": SOURCE_SHA, "digest": WORKER_DIGEST}]


def test_api_release_identity_returns_service_unavailable_without_revision(monkeypatch) -> None:
    monkeypatch.setenv("SOURCE_SHA", SOURCE_SHA)
    monkeypatch.setenv("API_IMAGE_DIGEST", API_DIGEST)
    monkeypatch.setattr(release_identity, "ALEMBIC_REVISION_PATH", ROOT / "missing-revision")
    app = create_app()

    async def current_user() -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=1)

    app.dependency_overrides[get_current_user] = current_user

    response = TestClient(app).get("/release/identity")

    assert response.status_code == 503


def test_worker_release_identity_returns_service_unavailable_when_store_fails() -> None:
    app = create_app()

    async def failed_worker_identity() -> list[ServiceIdentity]:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="Worker identity unavailable")

    async def current_user() -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=1)

    app.dependency_overrides[resolve_worker_identity] = failed_worker_identity
    app.dependency_overrides[get_current_user] = current_user

    response = TestClient(app, raise_server_exceptions=False).get("/release/worker-identity")

    assert response.status_code == 503


def test_worker_release_identity_authenticates_before_reading_store() -> None:
    app = create_app()
    store_calls = 0

    async def stored_worker_identity() -> list[ServiceIdentity]:
        nonlocal store_calls
        store_calls += 1
        return [ServiceIdentity(source_sha=SOURCE_SHA, digest=WORKER_DIGEST)]

    app.dependency_overrides[resolve_worker_identity] = stored_worker_identity

    response = TestClient(app).get("/release/worker-identity")

    assert response.status_code == 401
    assert store_calls == 0
