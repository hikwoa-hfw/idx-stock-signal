import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import joblib
from pydantic import BaseModel, Field, field_validator, model_validator

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
    status: str = "challenger"  # "champion", "challenger", "archived_champion", or "retired"
    feature_names: list[str] = Field(default_factory=list)
    mode: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mode_id(self) -> Optional[str]:
        return self.mode

    @model_validator(mode="before")
    @classmethod
    def _normalize_mode_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "mode_id" in data and "mode" not in data:
                data["mode"] = data["mode_id"]
        return data

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in ("champion", "challenger", "archived_champion", "retired"):
            raise ValueError(
                "status must be 'champion', 'challenger', 'archived_champion', "
                f"or 'retired', got '{v}'"
            )
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
                task=metadata.task,
                mode=metadata.mode,
                exclude_version=metadata.model_version,
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

    def list_models(
        self,
        task: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> list[ModelMetadata]:
        """List all registered models, sorted by creation date descending."""
        models: list[ModelMetadata] = []
        for p in self.registry_dir.glob("*.json"):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                meta = ModelMetadata(**raw)
                if task is not None and meta.task.lower() != task.lower():
                    continue
                if mode is not None:
                    meta_mode = (meta.mode or "").strip().upper()
                    target_mode = mode.strip().upper()
                    if meta_mode != target_mode:
                        continue
                models.append(meta)
            except Exception:
                continue

        models.sort(key=lambda m: (m.created_at, m.model_version), reverse=True)
        return models

    def get_champion(
        self,
        task: str = "classification",
        mode: Optional[str] = None,
    ) -> Optional[tuple[Any, ModelMetadata]]:
        """Get the current champion model and metadata for a task, optionally mode-specific."""
        for meta in self.list_models(task=task, mode=mode):
            if meta.status.lower() == "champion":
                return self.load_model(meta.model_version)
        return None

    def promote_to_champion(
        self,
        model_version: str,
        demote_to: str = "challenger",
        mode: Optional[str] = None,
    ) -> ModelMetadata:
        """Promote a model to champion status, demoting previous champion in same mode."""
        meta = self.get_metadata(model_version)
        effective_mode = mode if mode is not None else meta.mode
        self._demote_existing_champions(
            task=meta.task,
            mode=effective_mode,
            exclude_version=model_version,
            demote_to=demote_to,
        )

        meta.status = "champion"
        if mode is not None:
            meta.mode = mode
        meta_path = self._metadata_path(model_version)
        meta_path.write_text(meta.model_dump_json_pretty(), encoding="utf-8")
        return meta

    def rollback_champion(
        self,
        target_version: Optional[str] = None,
        task: str = "classification",
        mode: Optional[str] = None,
        demote_current_to: str = "retired",
    ) -> ModelMetadata:
        """Revert champion to target_version or last known champion in mode."""
        current_champ = self.get_champion(task=task, mode=mode)
        current_ver = current_champ[1].model_version if current_champ else None

        if target_version:
            target_meta = self.get_metadata(target_version)
            eff_mode = mode if mode is not None else target_meta.mode
            if target_meta.task.lower() != task.lower():
                raise ValueError(
                    f"Target model '{target_version}' task '{target_meta.task}' "
                    f"does not match requested task '{task}'."
                )
            if current_ver and target_meta.model_version == current_ver:
                raise ValueError(
                    f"Model '{target_version}' is already the active champion for task '{task}'."
                )
        else:
            eff_mode = mode
            candidates = [
                m for m in self.list_models(task=task, mode=mode)
                if m.model_version != current_ver
            ]
            archived = [m for m in candidates if m.status.lower() == "archived_champion"]
            if archived:
                target_meta = archived[0]
            elif candidates:
                target_meta = candidates[0]
            else:
                mode_str = f" mode={mode}" if mode else ""
                raise ValueError(
                    f"No prior models found in registry for rollback (task={task}{mode_str})."
                )

        self.promote_to_champion(
            target_meta.model_version,
            demote_to=demote_current_to,
            mode=eff_mode,
        )
        return self.get_metadata(target_meta.model_version)

    def _demote_existing_champions(
        self,
        task: str,
        mode: Optional[str] = None,
        exclude_version: Optional[str] = None,
        demote_to: str = "challenger",
    ) -> None:
        for meta in self.list_models(task=task):
            if exclude_version and meta.model_version == exclude_version:
                continue
            if mode is not None:
                meta_mode = (meta.mode or "").strip().upper()
                if meta_mode != mode.strip().upper():
                    continue
            else:
                if meta.mode is not None:
                    continue
            if meta.status.lower() == "champion":
                meta.status = demote_to
                path = self._metadata_path(meta.model_version)
                path.write_text(meta.model_dump_json_pretty(), encoding="utf-8")
