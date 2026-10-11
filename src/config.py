"""Project paths and optional runtime numbers.

The notes vault is chosen by the user and remembered as ``VAULT`` in ``.env``.
The workspace for that vault is ``<vault>/.assistant``. Skills live in ``skills/``.
Sessions live in ``sessions/``.

``settings.toml`` may override the step limits and compaction thresholds.
A missing file, or a missing key, keeps the defaults below.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
VAULT_FILE = ROOT / ".vault"
SETTINGS_FILE = ROOT / "settings.toml"
ASSISTANT_DIR = ".assistant"
_VAULT_KEY = "VAULT"

DEFAULT_MAX_STEPS = 128
DEFAULT_SUBTASK_STEPS = 40
DEFAULT_COMPACT_LIGHT = 40_000
DEFAULT_COMPACT_HEAVY = 100_000
_SETTING_KEYS = ("max_steps", "subtask_steps", "compact_light", "compact_heavy")


@dataclass(frozen=True)
class Settings:
    """Step limits and compaction thresholds for one process."""

    max_steps: int = DEFAULT_MAX_STEPS
    subtask_steps: int = DEFAULT_SUBTASK_STEPS
    compact_light: int = DEFAULT_COMPACT_LIGHT
    compact_heavy: int = DEFAULT_COMPACT_HEAVY


def load_settings() -> Settings:
    """Read ``settings.toml``. Absent keys stay at the program defaults."""
    if not SETTINGS_FILE.is_file():
        return Settings()
    try:
        data = tomllib.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"settings.toml: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("settings.toml must set numbers at the top level")
    unknown = sorted(set(data) - set(_SETTING_KEYS))
    if unknown:
        raise ValueError("settings.toml has unknown settings: " + ", ".join(unknown))
    values: dict[str, int] = {}
    for key in _SETTING_KEYS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"settings.toml {key} must be a positive integer")
        values[key] = value
    settings = Settings(**values)
    if settings.compact_heavy < settings.compact_light:
        raise ValueError("settings.toml compact_heavy must be at least compact_light")
    return settings


def assistant_dir(vault: str | Path) -> Path:
    """Agent files for one notes vault. A dot directory stays out of note search."""
    return Path(vault).resolve() / ASSISTANT_DIR


def load_vault() -> Path | None:
    """The notes vault from the environment or ``.env``, if that directory still exists."""
    text = _env_value(_VAULT_KEY)
    if text:
        path = Path(text)
        return path if path.is_dir() else None
    legacy = _legacy_vault()
    if legacy is None:
        return None
    return save_vault(legacy)


def save_vault(vault: str | Path) -> Path:
    """Remember a notes vault in ``.env``. The directory must already exist."""
    path = Path(vault).resolve()
    if not path.is_dir():
        raise NotADirectoryError(f"notes vault is not a directory: {path}")
    _set_env_line(_VAULT_KEY, str(path))
    os.environ[_VAULT_KEY] = str(path)
    return path


def _env_value(name: str) -> str:
    if name in os.environ:
        return os.environ[name].strip()
    return _file_value(name)


def _file_value(name: str) -> str:
    if not ENV_FILE.is_file():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key.strip() == name:
            return value.strip()
    return ""


def _set_env_line(name: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []
    replaced = False
    updated: list[str] = []
    for line in lines:
        key, separator, _old = line.partition("=")
        if separator and key.strip() == name and not line.lstrip().startswith("#"):
            updated.append(f"{name}={value}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        updated.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _legacy_vault() -> Path | None:
    if not VAULT_FILE.is_file():
        return None
    text = VAULT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_dir() else None
