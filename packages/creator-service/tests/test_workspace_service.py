import asyncio

from creator_service.workspace_service import InMemoryWorkspaceStorage, WorkspaceService


def run(coro):
    return asyncio.run(coro)


def test_create_workspace_adds_owner_membership() -> None:
    storage = InMemoryWorkspaceStorage()
    service = WorkspaceService(storage)

    workspace = run(service.create_workspace(name="Studio", slug="studio", owner_id=42))

    assert workspace.id == 1
    assert workspace.owner_id == 42
    assert run(service.check_access(workspace.id, 42))


def test_add_member_and_check_access() -> None:
    storage = InMemoryWorkspaceStorage()
    service = WorkspaceService(storage)
    workspace = run(service.create_workspace(name="Studio", slug="studio", owner_id=1))

    member = run(service.add_member(workspace.id, 2, role="member"))

    assert member.workspace_id == workspace.id
    assert member.user_id == 2
    assert member.role == "member"
    assert run(service.check_access(workspace.id, 2))


def test_list_user_workspaces_returns_only_member_workspaces() -> None:
    storage = InMemoryWorkspaceStorage()
    service = WorkspaceService(storage)
    first = run(service.create_workspace(name="One", slug="one", owner_id=7))
    second = run(service.create_workspace(name="Two", slug="two", owner_id=8))

    run(service.add_member(first.id, 9))

    workspaces = run(service.list_user_workspaces(9))

    assert len(workspaces) == 1
    assert workspaces[0].id == first.id
    assert workspaces[0].id != second.id
