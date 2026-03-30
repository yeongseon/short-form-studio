"""Artifact storage service for managing project artifacts locally."""

import os
import shutil
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class ArtifactType(Enum):
    """Enumeration of artifact types."""

    SCRIPTS = "scripts"
    VISUAL_PLANS = "visual-plans"
    IMAGES = "images"
    AUDIO = "audio"
    SUBTITLES = "subtitles"
    RENDERS = "renders"
    THUMBNAILS = "thumbnails"


@dataclass
class ArtifactPath:
    """Represents a path to an artifact in the storage structure."""

    project_id: str
    run_id: str
    artifact_type: ArtifactType
    filename: str | None = None

    def to_path(self, root: Path) -> Path:
        """Convert to full filesystem path."""
        p = root / self.project_id / self.run_id / self.artifact_type.value
        if self.filename:
            p = p / self.filename
        return p


class ArtifactService:
    """Service for managing artifact storage and retrieval."""

    def __init__(self, root: str | None = None):
        """Initialize the artifact service.

        Args:
            root: Root directory for artifact storage. Defaults to ARTIFACT_ROOT env var
                  or ./data/artifacts if not specified.
        """
        self.root = Path(root or os.getenv("ARTIFACT_ROOT", "./data/artifacts"))

    def save(self, artifact: ArtifactPath, content: bytes) -> Path:
        """Save artifact content to local filesystem.

        Args:
            artifact: ArtifactPath specifying where to save
            content: Binary content to save

        Returns:
            Path to saved artifact
        """
        path = artifact.to_path(self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def load(self, artifact: ArtifactPath) -> bytes:
        """Load artifact content from local filesystem.

        Args:
            artifact: ArtifactPath specifying what to load

        Returns:
            Binary content of the artifact

        Raises:
            FileNotFoundError: If artifact does not exist
        """
        path = artifact.to_path(self.root)
        if not path.exists():
            raise FileNotFoundError(f"Artifact not found: {path}")
        return path.read_bytes()

    def list_artifacts(
        self, project_id: str, run_id: str, artifact_type: ArtifactType
    ) -> list[str]:
        """List artifact filenames for a given type in a run.

        Args:
            project_id: Project identifier
            run_id: Run identifier
            artifact_type: Type of artifacts to list

        Returns:
            Sorted list of artifact filenames in the directory
        """
        path = ArtifactPath(project_id, run_id, artifact_type).to_path(self.root)
        if not path.exists():
            return []
        return sorted(f.name for f in path.iterdir() if f.is_file())

    def delete(self, artifact: ArtifactPath) -> bool:
        """Delete a specific artifact file.

        Args:
            artifact: ArtifactPath specifying what to delete

        Returns:
            True if deleted, False if file did not exist
        """
        path = artifact.to_path(self.root)
        if path.exists() and path.is_file():
            path.unlink()
            return True
        return False

    def delete_run(self, project_id: str, run_id: str) -> bool:
        """Delete all artifacts for a run.

        Args:
            project_id: Project identifier
            run_id: Run identifier

        Returns:
            True if deleted, False if directory did not exist
        """
        path = self.root / project_id / run_id
        if path.exists():
            shutil.rmtree(path)
            return True
        return False

    def ensure_run_dirs(self, project_id: str, run_id: str) -> None:
        """Create all artifact type directories for a run.

        Args:
            project_id: Project identifier
            run_id: Run identifier
        """
        for art_type in ArtifactType:
            (self.root / project_id / run_id / art_type.value).mkdir(
                parents=True, exist_ok=True
            )
