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
