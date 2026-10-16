from pathlib import Path

from pydantic import BaseModel, Field
import yaml


ROOT = Path(__file__).resolve().parents[3]
OPT_IN = "vars.DEPLOYMENT_ENABLED == 'true'"


class Job(BaseModel):
    condition: str = Field(default="", alias="if")
    needs: str | list[str] = Field(default_factory=list)


class Workflow(BaseModel):
    jobs: dict[str, Job]


def test_delivery_entry_points_require_explicit_opt_in() -> None:
    # Given the parsed workflow used for both main pushes and manual dispatch.
    workflow = Workflow.model_validate(yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text()))
    # When traversing all dependency paths, including jobs that bypass skipped needs.
    protected: set[str] = set()
    pending = dict(workflow.jobs)
    while pending:
        ready = [name for name, job in pending.items()
                 if set([job.needs] if isinstance(job.needs, str) else job.needs).isdisjoint(pending)]
        assert ready, "CD dependency graph must be acyclic"
        for name in ready:
            job = pending.pop(name)
            dependencies = [job.needs] if isinstance(job.needs, str) else job.needs
            expression = job.condition.removeprefix("${{").removesuffix("}}").strip()
            guarded = expression.startswith(f"{OPT_IN} && ") or expression.startswith(f"always() && {OPT_IN} && ")
            inherited = bool(set(dependencies) & protected) and "always()" not in expression
            # Then every job is gated directly or inherits a successful gated dependency.
            assert guarded or inherited, f"{name} can run without explicit deployment opt-in"
            protected.add(name)


def test_ci_waits_use_immutable_commit() -> None:
    # Given the delivery workflow, when reading the actual wait action inputs.
    workflow = yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())
    waits = workflow["jobs"]["wait-for-ci"]["steps"]
    # Then a moving main ref cannot certify a different source revision.
    assert all(step["with"]["ref"] == "${{ github.sha }}" for step in waits)


def test_release_preflight_precedes_every_migration_and_deploy() -> None:
    # Given the parsed CD graph, when inspecting state-changing jobs.
    workflow = Workflow.model_validate(yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text()))
    jobs = workflow.jobs

    # Then preflight is a direct dependency and the explicit hold remains on every entry.
    for name in ("migrate-staging", "deploy-staging", "migrate-production", "deploy-production"):
        needs = jobs[name].needs
        dependencies = [needs] if isinstance(needs, str) else needs
        assert "release-preflight" in dependencies, name
        assert OPT_IN in jobs[name].condition, name


def test_scan_gates_release_promotion_and_latest() -> None:
    # Given candidate publication and promotion jobs.
    raw = yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())
    jobs = raw["jobs"]

    # When reading promotion dependencies and commands, then scans and opt-in gate approval.
    promotion = jobs["promote-release"]
    needs = promotion["needs"]
    assert "trivy-scan" in ([needs] if isinstance(needs, str) else needs)
    assert OPT_IN in promotion["if"]
    assert "latest" in "\n".join(step.get("run", "") for step in promotion["steps"])
    candidate = jobs["build-candidate"]
    candidate_tags = "\n".join(
        str(step.get("with", {}).get("tags", "")) for step in candidate["steps"]
    )
    assert ":latest" not in candidate_tags
    assert "aquasecurity/trivy-action@master" not in str(jobs["trivy-scan"])


def test_manual_dispatch_selects_a_successful_prior_run_artifact() -> None:
    raw = yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())

    inputs = raw[True]["workflow_dispatch"]["inputs"]
    assert "release_run_id" in inputs
    assert "release_manifest" not in inputs
    preflight = raw["jobs"]["release-preflight"]
    commands = "\n".join(step.get("run", "") for step in preflight["steps"])
    downloads = [step for step in preflight["steps"] if step.get("uses") == "actions/download-artifact@v4"]
    assert "actions/runs/$RELEASE_RUN_ID" in commands
    assert "conclusion" in commands and "success" in commands
    assert "workflow_id" in commands and "cd.yml" in commands
    assert any(step.get("with", {}).get("run-id") == "${{ github.event.inputs.release_run_id }}" for step in downloads)


def test_registry_jobs_authenticate_and_install_pinned_validator_dependencies() -> None:
    raw = yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())

    for name in ("trivy-scan", "create-manifest", "promote-release", "release-preflight"):
        steps = raw["jobs"][name]["steps"]
        assert any(step.get("uses") == "docker/login-action@v3" for step in steps), name
    for name in ("create-manifest", "release-preflight"):
        commands = "\n".join(step.get("run", "") for step in raw["jobs"][name]["steps"])
        assert "pydantic==" in commands, name


def test_rollback_migration_uses_selected_release_image_and_requires_downgrade_approval() -> None:
    # Given manual rollback and database downgrade jobs.
    raw = yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())
    jobs = raw["jobs"]

    # Then app rollback has no migration, while downgrade is separate and image-bound.
    rollback = str(jobs["deploy-production"])
    assert "alembic" not in rollback
    downgrade = jobs["downgrade-production"]
    assert "github.event.inputs.approve_db_downgrade == 'DOWNGRADE'" in downgrade["if"]
    commands = "\n".join(step.get("run", "") for step in downgrade["steps"])
    assert "docker run" in commands
    assert "$API_IMAGE@$CURRENT_API_DIGEST" in commands
    assert "alembic downgrade" not in "\n".join(
        step.get("run", "") for step in downgrade["steps"] if step.get("uses") == "actions/checkout@v4"
    )
    assert "downgrade_revision:" not in (ROOT / ".github/workflows/cd.yml").read_text()
    assert any(
        step.get("env", {}).get("TARGET_REVISION") == "${{ needs.release-preflight.outputs.db_revision }}"
        for step in downgrade["steps"]
    )
    assert "alembic current" in commands
    assert "verify-db" in commands

    for name in ("migrate-staging", "migrate-production"):
        assert "github.event.inputs.release_action == 'deploy'" in jobs[name]["if"]


def test_post_deploy_smoke_downloads_the_created_nonempty_resource() -> None:
    raw = yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())
    jobs = raw["jobs"]

    for name in ("verify-staging", "verify-production"):
        commands = "\n".join(step.get("run", "") for step in jobs[name]["steps"])
        assert "jq -er" in commands, name
        assert "SMOKE_DOWNLOAD_BASE_URL" in commands, name
        assert "${resource_id}" in commands, name
        assert "test -s download.bin" in commands, name


def test_deploy_production_condition_references_only_direct_needs() -> None:
    workflow = Workflow.model_validate(yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text()))

    job = workflow.jobs["deploy-production"]
    dependencies = {job.needs} if isinstance(job.needs, str) else set(job.needs)
    referenced = {
        token.split(".")[1]
        for token in job.condition.replace("${{", "").replace("}}", "").split()
        if token.startswith("needs.") and token.count(".") >= 2
    }
    assert referenced <= dependencies


def test_promotion_finishes_all_immutable_tags_before_latest() -> None:
    raw = yaml.safe_load((ROOT / ".github/workflows/cd.yml").read_text())
    commands = "\n".join(step.get("run", "") for step in raw["jobs"]["promote-release"]["steps"])

    assert commands.count("for target in") >= 2
    assert commands.find('crane tag "$target" "$RELEASE_TAG"') < commands.rfind('crane tag "$target" latest')


def test_workflow_has_no_reachable_placeholder_targets() -> None:
    # Given the active CD workflow, then no example/TODO target can reach shell execution.
    text = (ROOT / ".github/workflows/cd.yml").read_text().lower()
    assert "example.com" not in text
    assert "todo" not in text
