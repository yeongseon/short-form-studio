"""Unit tests for artifact service."""

import pytest
from pathlib import Path

from creator_service import ArtifactService, ArtifactType, ArtifactPath


class TestArtifactService:
    """Tests for ArtifactService class."""

    @pytest.fixture
    def service(self, tmp_path):
        """Create a service instance with temporary directory."""
        return ArtifactService(root=str(tmp_path))

    @pytest.fixture
    def project_id(self):
        """Test project ID."""
        return "test-project"

    @pytest.fixture
    def run_id(self):
        """Test run ID."""
        return "run-001"

    def test_save_and_load_roundtrip(self, service, project_id, run_id):
        """Test save and load operations create roundtrip."""
        content = b"test artifact content"
        artifact = ArtifactPath(
            project_id=project_id,
            run_id=run_id,
            artifact_type=ArtifactType.SCRIPTS,
            filename="test.py",
        )

        # Save
        saved_path = service.save(artifact, content)
        assert saved_path.exists()

        # Load
        loaded_content = service.load(artifact)
        assert loaded_content == content

    def test_save_creates_directory_structure(self, service, project_id, run_id):
        """Test that save creates required directory structure."""
        content = b"test"
        artifact = ArtifactPath(
            project_id=project_id,
            run_id=run_id,
            artifact_type=ArtifactType.IMAGES,
            filename="img.png",
        )

        service.save(artifact, content)

        expected_dir = (
            service.root / project_id / run_id / ArtifactType.IMAGES.value
        )
        assert expected_dir.exists()
        assert (expected_dir / "img.png").exists()

    def test_list_artifacts_returns_filenames(self, service, project_id, run_id):
        """Test list_artifacts returns correct sorted filenames."""
        # Save multiple artifacts
        for i in range(3):
            artifact = ArtifactPath(
                project_id=project_id,
                run_id=run_id,
                artifact_type=ArtifactType.SCRIPTS,
                filename=f"script_{i}.py",
            )
            service.save(artifact, b"content")

        # List
        files = service.list_artifacts(project_id, run_id, ArtifactType.SCRIPTS)
        assert files == ["script_0.py", "script_1.py", "script_2.py"]

    def test_list_artifacts_empty_directory(self, service, project_id, run_id):
        """Test list_artifacts returns empty list for non-existent directory."""
        files = service.list_artifacts(project_id, run_id, ArtifactType.AUDIO)
        assert files == []

    def test_delete_removes_file(self, service, project_id, run_id):
        """Test delete removes a specific artifact file."""
        content = b"test content"
        artifact = ArtifactPath(
            project_id=project_id,
            run_id=run_id,
            artifact_type=ArtifactType.SUBTITLES,
            filename="subs.vtt",
        )

        service.save(artifact, content)
        assert service.delete(artifact) is True

        # Verify file is gone
        with pytest.raises(FileNotFoundError):
            service.load(artifact)

    def test_delete_nonexistent_file(self, service, project_id, run_id):
        """Test delete returns False for non-existent file."""
        artifact = ArtifactPath(
            project_id=project_id,
            run_id=run_id,
            artifact_type=ArtifactType.RENDERS,
            filename="missing.mp4",
        )

        assert service.delete(artifact) is False

    def test_load_raises_file_not_found(self, service, project_id, run_id):
        """Test load raises FileNotFoundError for missing artifact."""
        artifact = ArtifactPath(
            project_id=project_id,
            run_id=run_id,
            artifact_type=ArtifactType.THUMBNAILS,
            filename="missing.jpg",
        )

        with pytest.raises(FileNotFoundError):
            service.load(artifact)

    def test_delete_run_removes_entire_directory(self, service, project_id, run_id):
        """Test delete_run removes all artifacts for a run."""
        # Save artifacts of different types
        for art_type in [ArtifactType.SCRIPTS, ArtifactType.IMAGES]:
            artifact = ArtifactPath(
                project_id=project_id,
                run_id=run_id,
                artifact_type=art_type,
                filename="file.txt",
            )
            service.save(artifact, b"content")

        # Delete run
        assert service.delete_run(project_id, run_id) is True

        # Verify directory is gone
        run_path = service.root / project_id / run_id
        assert not run_path.exists()

    def test_delete_run_nonexistent(self, service, project_id, run_id):
        """Test delete_run returns False for non-existent run."""
        assert service.delete_run(project_id, run_id) is False

    def test_ensure_run_dirs_creates_all_artifact_types(self, service, project_id, run_id):
        """Test ensure_run_dirs creates all 7 artifact type directories."""
        service.ensure_run_dirs(project_id, run_id)

        # Verify all directories exist
        for art_type in ArtifactType:
            dir_path = service.root / project_id / run_id / art_type.value
            assert dir_path.exists()
            assert dir_path.is_dir()

    def test_ensure_run_dirs_count(self, service, project_id, run_id):
        """Test ensure_run_dirs creates exactly 7 directories."""
        service.ensure_run_dirs(project_id, run_id)

        run_path = service.root / project_id / run_id
        subdirs = [d for d in run_path.iterdir() if d.is_dir()]
        assert len(subdirs) == 7

    def test_artifact_path_with_no_filename(self, tmp_path):
        """Test ArtifactPath.to_path without filename."""
        artifact = ArtifactPath(
            project_id="p1",
            run_id="r1",
            artifact_type=ArtifactType.IMAGES,
        )

        path = artifact.to_path(tmp_path)
        assert path == tmp_path / "p1" / "r1" / "images"

    def test_artifact_path_with_filename(self, tmp_path):
        """Test ArtifactPath.to_path with filename."""
        artifact = ArtifactPath(
            project_id="p1",
            run_id="r1",
            artifact_type=ArtifactType.RENDERS,
            filename="output.mp4",
        )

        path = artifact.to_path(tmp_path)
        assert path == tmp_path / "p1" / "r1" / "renders" / "output.mp4"

    def test_service_default_root(self, monkeypatch):
        """Test service uses default root directory."""
        # Unset ARTIFACT_ROOT
        monkeypatch.delenv("ARTIFACT_ROOT", raising=False)

        service = ArtifactService()
        assert service.root == Path("./data/artifacts")

    def test_service_env_root(self, monkeypatch, tmp_path):
        """Test service respects ARTIFACT_ROOT environment variable."""
        monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))

        service = ArtifactService()
        assert service.root == tmp_path

    def test_service_explicit_root(self, tmp_path):
        """Test service uses explicit root parameter."""
        service = ArtifactService(root=str(tmp_path))
        assert service.root == tmp_path
