import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import joblib
from pydantic import BaseModel, Field, field_validator

from python.config.settings import settings


class ModelMetadata(BaseModel):
    model_version: str
    algorithm: str
    task: str = "classification"
    dataset_version: str = "v1.0.0"
    feature_version: str = "v1.0.0"
    training_start: str
    training_end: str
    validation_start: Optional[str] = None
    validation_end: Optional[str] = None
    metrics: dict[str, float] = Field(default_factory=dict)
    status: str = "challenger"  # "champion" or "challenger"
    feature_names: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("champion", "challenger"):
            raise ValueError(f"status must be 'champion' or 'challenger', got '{v}'")
        return s

    def model_dump_json_pretty(self) -> str:
        d = self.model_dump(mode="json")
        return json.dumps(d, indent=2)


class ModelRegistry:
    """Manages serialization, versioning, and status (champion/challenger) of model artifacts."""

    def __init__(self, registry_dir: Optional[Union[str, Path]] = None) -> None:
        self.registry_dir = (
            Path(registry_dir) if registry_dir is not None else settings.model_registry_path
        )
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    def _artifact_path(self, model_version: str) -> Path:
        return self.registry_dir / f"{model_version}.joblib"

    def _metadata_path(self, model_version: str) -> Path:
        return self.registry_dir / f"{model_version}.json"

    def save_model(self, model: Any, metadata: ModelMetadata) -> Path:
        """Saves model via joblib and metadata as JSON."""
        if metadata.status.lower() == "champion":
            self._demote_existing_champions(
                task=metadata.task, exclude_version=metadata.model_version
            )

        art_path = self._artifact_path(metadata.model_version)
        meta_path = self._metadata_path(metadata.model_version)

        joblib.dump(model, art_path)
        meta_path.write_text(metadata.model_dump_json_pretty(), encoding="utf-8")
        return art_path

    def load_model(self, model_version: str) -> tuple[Any, ModelMetadata]:
        """Loads model artifact and its metadata by version string."""
        art_path = self._artifact_path(model_version)
        meta_path = self._metadata_path(model_version)

        if not art_path.is_file():
            raise FileNotFoundError(f"Artifact not found for version '{model_version}': {art_path}")
        if not meta_path.is_file():
            raise FileNotFoundError(
                f"Metadata not found for version '{model_version}': {meta_path}"
            )

        raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        metadata = ModelMetadata(**raw_meta)
        model = joblib.load(art_path)
        return model, metadata

    def get_metadata(self, model_version: str) -> ModelMetadata:
        meta_path = self._metadata_path(model_version)
        if not meta_path.is_file():
            raise FileNotFoundError(
                f"Metadata not found for version '{model_version}': {meta_path}"
            )
        raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return ModelMetadata(**raw_meta)

    def list_models(self, task: Optional[str] = None) -> list[ModelMetadata]:
        """List all registered models, sorted by creation date descending."""
        models: list[ModelMetadata] = []
        for p in self.registry_dir.glob("*.json"):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                meta = ModelMetadata(**raw)
                if task is None or meta.task.lower() == task.lower():
                    models.append(meta)
            except Exception:
                continue

        models.sort(key=lambda m: m.created_at, reverse=True)
        return models

    def get_champion(self, task: str = "classification") -> Optional[tuple[Any, ModelMetadata]]:
        """Get the current champion model and metadata for a task."""
        for meta in self.list_models(task=task):
            if meta.status.lower() == "champion":
                return self.load_model(meta.model_version)
        return None

    def promote_to_champion(self, model_version: str) -> ModelMetadata:
        """Promote a challenger model to champion status, demoting previous champion."""
        meta = self.get_metadata(model_version)
        self._demote_existing_champions(task=meta.task, exclude_version=model_version)

        meta.status = "champion"
        meta_path = self._metadata_path(model_version)
        meta_path.write_text(meta.model_dump_json_pretty(), encoding="utf-8")
        return meta

    def _demote_existing_champions(self, task: str, exclude_version: Optional[str] = None) -> None:
        for meta in self.list_models(task=task):
            if exclude_version and meta.model_version == exclude_version:
                continue
            if meta.status.lower() == "champion":
                meta.status = "challenger"
                path = self._metadata_path(meta.model_version)
                path.write_text(meta.model_dump_json_pretty(), encoding="utf-8")
