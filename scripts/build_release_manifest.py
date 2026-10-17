#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
IMAGES = {
    "api": "apps/api/Dockerfile",
    "worker": "apps/worker-orchestrator/Dockerfile",
    "web": "apps/studio-web/Dockerfile",
}
REGISTRY = "127.0.0.1:5000"


def run(*command: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def main() -> int:
    output = Path(sys.argv[1])
    manifest: dict[str, str] = {}
    for name, dockerfile in IMAGES.items():
        image = f"{REGISTRY}/short-form-studio-{name}:restore-test"
        run(
            "docker", "build", "--target", "runtime", "-f", dockerfile,
            "-t", image, str(ROOT),
        )
        run("docker", "push", image)
        repo_digests = run(
            "docker", "image", "inspect", image,
            "--format={{join .RepoDigests \"\\n\"}}",
        ).splitlines()
        digest = next((value for value in repo_digests if "@sha256:" in value), None)
        if digest is None:
            raise RuntimeError(f"built image lacks RepoDigest: {name}")
        manifest[name] = digest
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
