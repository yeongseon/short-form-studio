import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[3]
SOURCE_SHA = "b" * 40
STUDIO_DIGEST = "sha256:" + "c" * 64


def test_docker_images_embed_source_revision_and_studio_artifact() -> None:
    for path in (
        ROOT / "apps/api/Dockerfile",
        ROOT / "apps/worker-orchestrator/Dockerfile",
        ROOT / "apps/studio-web/Dockerfile",
    ):
        dockerfile = path.read_text()
        assert "ARG SOURCE_SHA" in dockerfile, path
        assert "org.opencontainers.image.revision" in dockerfile, path

    studio = (ROOT / "apps/studio-web/Dockerfile").read_text()
    assert "40-release-identity.sh" in studio
    artifact_script = (ROOT / "apps/studio-web/docker-entrypoint.d/40-release-identity.sh").read_text()
    assert "release-identity.json" in artifact_script
    assert "STUDIO_IMAGE_DIGEST" in artifact_script

    api = (ROOT / "apps/api/Dockerfile").read_text()
    assert "mapfile -t revisions" in api
    assert 'test "${#revisions[@]}" -eq 1' in api


def test_studio_entrypoint_writes_runtime_digest(tmp_path: Path) -> None:
    (tmp_path / "source-sha").write_text(SOURCE_SHA)
    script = ROOT / "apps/studio-web/docker-entrypoint.d/40-release-identity.sh"
    environment = os.environ | {
        "STUDIO_WEB_ROOT": str(tmp_path),
        "STUDIO_IMAGE_DIGEST": STUDIO_DIGEST,
    }

    subprocess.run(["sh", str(script)], env=environment, check=True)

    assert json.loads((tmp_path / "release-identity.json").read_text()) == {
        "source_sha": SOURCE_SHA,
        "digest": STUDIO_DIGEST,
    }


def test_studio_entrypoint_allows_local_start_without_release_digest(tmp_path: Path) -> None:
    # Given a locally built Studio image without registry digest metadata.
    (tmp_path / "source-sha").write_text("")
    script = ROOT / "apps/studio-web/docker-entrypoint.d/40-release-identity.sh"
    environment = (os.environ | {"STUDIO_WEB_ROOT": str(tmp_path)})
    environment.pop("STUDIO_IMAGE_DIGEST", None)

    # When the container entrypoint initializes its static files.
    subprocess.run(["sh", str(script)], env=environment, check=True)

    # Then nginx startup is not blocked and no false release identity is exposed.
    assert not (tmp_path / "release-identity.json").exists()
