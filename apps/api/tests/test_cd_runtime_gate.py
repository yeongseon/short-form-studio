from pathlib import Path

import yaml


def test_cd_waits_for_every_release_check_present_in_ci() -> None:
    # Given the actual CI/CD definitions at this boundary.
    root = Path(__file__).resolve().parents[3] / ".github/workflows"
    ci = yaml.safe_load((root / "ci.yml").read_text())
    cd = yaml.safe_load((root / "cd.yml").read_text())
    # When collecting the release check names from the wait actions.
    waits = {step["with"]["check-name"]: step["with"]["ref"]
             for step in cd["jobs"]["wait-for-ci"]["steps"]}
    # Then the new runtime job cannot be omitted or checked on a moving branch.
    for name in ("lint", "test", "docker", "first-short-runtime"):
        if name in ci["jobs"]:
            assert waits.get(name) == "${{ github.sha }}", name
