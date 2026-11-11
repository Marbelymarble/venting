"""Persistent directory preference; journal contents never enter settings."""

import json
import os
from pathlib import Path
import tempfile

from .autocorrect import validate_language
from .shortcuts import DEFAULT_BINDINGS, validate_bindings
from .summaries import validate_model
from .topicmap import validate_days


def default_locations() -> tuple[Path, str]:
    project = Path(__file__).resolve().parent.parent
    if (project / "run").is_file() and (project / "pyproject.toml").is_file():
        return project / "venting.json", "vents"
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return config / "venting/config.json", str(data / "venting/vents")


class Settings:
    def __init__(self, config_path: Path | None = None):
        location, directory = default_locations() if config_path is None else (config_path, "vents")
        self.config_path = Path(location).expanduser().resolve()
        self.values: dict = {
            "default_directory": directory,
            "summary_model": "",
            "show_recent_vents": True,
            "autocorrect_language": "en",
            "topic_map_days": 30,
            "keybindings": dict(DEFAULT_BINDINGS),
        }

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Settings":
        settings = cls(config_path)
        try:
            raw = settings.config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return settings
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("Settings file is not valid JSON.") from None
        if not isinstance(values, dict):
            raise ValueError("Settings must be a JSON object.")
        settings.values.update(values)
        settings._resolve_directory(settings.directory_value)
        if settings.summary_model != "":
            validate_model(settings.summary_model)
        if not isinstance(settings.show_recent_vents, bool):
            raise ValueError("show_recent_vents must be true or false.")
        validate_language(settings.autocorrect_language)
        validate_days(settings.topic_map_days)
        settings.values["keybindings"] = validate_bindings(settings.values.get("keybindings"))
        return settings

    @property
    def summary_model(self) -> str:
        return self.values.get("summary_model", "")

    @property
    def show_recent_vents(self) -> bool:
        return self.values.get("show_recent_vents", True)

    @property
    def directory_value(self) -> str:
        return self.values["default_directory"]

    @property
    def autocorrect_language(self) -> str:
        return self.values.get("autocorrect_language", "en")

    @property
    def keybindings(self) -> dict[str, str]:
        return validate_bindings(self.values.get("keybindings"))

    @property
    def topic_map_days(self) -> int:
        return self.values.get("topic_map_days", 30)

    def _resolve_directory(self, value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Enter a default directory.")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Directory paths cannot contain control characters.")
        path = Path(value.strip()).expanduser()
        if not path.is_absolute():
            path = self.config_path.parent / path
        return path.resolve()

    @property
    def default_directory(self) -> Path:
        return self._resolve_directory(self.directory_value)

    def ensure_directory(self) -> None:
        self.default_directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def set_preferences(self, directory_value: str, summary_model: str,
                        show_recent_vents: bool, autocorrect_language: str | None = None) -> None:
        directory = self._resolve_directory(directory_value)
        if summary_model:
            validate_model(summary_model)
        if not isinstance(show_recent_vents, bool):
            raise ValueError("Show recent vents must be on or off.")
        language = self.autocorrect_language if autocorrect_language is None else autocorrect_language
        validate_language(language)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not os.access(directory, os.W_OK | os.X_OK):
            raise PermissionError("Choose a directory you can write to.")
        updated = dict(
            self.values,
            default_directory=directory_value.strip(),
            summary_model=summary_model,
            show_recent_vents=show_recent_vents,
            autocorrect_language=language,
        )
        self._save(updated)

    def _save(self, updated: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Publish the new preference only after a complete atomic write.
        fd, name = tempfile.mkstemp(prefix=".venting-settings-", dir=self.config_path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as destination:
                json.dump(updated, destination, ensure_ascii=False, indent=2)
                destination.write("\n")
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, self.config_path)
        finally:
            temporary.unlink(missing_ok=True)
        self.values = updated

    def set_keybindings(self, keybindings: dict[str, str]) -> None:
        bindings = validate_bindings(keybindings)
        self._save(dict(self.values, keybindings=bindings))

    def set_directory(self, value: str) -> None:
        self.set_preferences(value, self.summary_model, self.show_recent_vents)

    def set_topic_map_days(self, days: int) -> None:
        self._save(dict(self.values, topic_map_days=validate_days(days)))
