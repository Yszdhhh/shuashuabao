"""Single canonical path provider for ShuaBao runtime, settings, locks, and logs.

Canonical base directory: %LOCALAPPDATA%\\ShuaBao (or $SHUABAO_APP_DATA).
Legacy compatibility: %USERPROFILE%\\AppData\\Local\\刷刷宝, %APPDATA%\\GameScript.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

LOGGER = logging.getLogger("ShuaBao")

APP_ID = "ShuaBao"
USER_SETTINGS_NAME = "user_settings.json"
LIVE_LOCK_NAME = "ShuaBao.live.lock"
HABIT_PREFERENCE_NAME = "habit_preference.json"
INCIDENTS_DIRNAME = "incidents"
LEARNING_DIRNAME = "learning"
PROFILES_DIRNAME = "profiles"
LIVE_LOG_NAME = "live.log"


def get_canonical_app_data_dir() -> Path:
    """Return the single canonical ShuaBao AppData directory.

    Priority:
    1. $SHUABAO_APP_DATA environment variable
    2. %LOCALAPPDATA%\\ShuaBao
    3. ~/.local/share/ShuaBao
    """
    override = os.environ.get("SHUABAO_APP_DATA", "").strip()
    if override:
        return Path(override).resolve()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return (Path(local) / APP_ID).resolve()
    return (Path.home() / ".local" / "share" / APP_ID).resolve()


def user_settings_path(app_data: Path | None = None) -> Path:
    base = Path(app_data) if app_data is not None else get_canonical_app_data_dir()
    return base / USER_SETTINGS_NAME


def live_lock_path(app_data: Path | None = None) -> Path:
    base = Path(app_data) if app_data is not None else get_canonical_app_data_dir()
    return base / LIVE_LOCK_NAME


def incidents_dir(app_data: Path | None = None) -> Path:
    base = Path(app_data) if app_data is not None else get_canonical_app_data_dir()
    return base / INCIDENTS_DIRNAME


def learning_dir(app_data: Path | None = None) -> Path:
    base = Path(app_data) if app_data is not None else get_canonical_app_data_dir()
    return base / LEARNING_DIRNAME


def habit_preference_path(app_data: Path | None = None) -> Path:
    base = Path(app_data) if app_data is not None else get_canonical_app_data_dir()
    return base / HABIT_PREFERENCE_NAME


def player_profile_dir(app_data: Path | None = None) -> Path:
    base = Path(app_data) if app_data is not None else get_canonical_app_data_dir()
    return base / PROFILES_DIRNAME


def live_log_path(app_data: Path | None = None) -> Path:
    base = Path(app_data) if app_data is not None else get_canonical_app_data_dir()
    return base / LIVE_LOG_NAME


def _legacy_candidate_dirs() -> list[Path]:
    """Known deployed legacy directories for non-destructive, idempotent migration."""
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        candidates.append(Path(local) / "刷刷宝")
    userprofile = os.environ.get("USERPROFILE", "").strip()
    if userprofile:
        candidates.append(Path(userprofile) / "AppData" / "Local" / "刷刷宝")
    return [p.resolve() for p in candidates if p.is_dir()]


def migrate_legacy_data(
    target_dir: Path | None = None,
    extra_candidates: list[Path] | None = None,
) -> list[str]:
    """Idempotently copy missing files from legacy directories to canonical target.

    Never deletes source files. Never overwrites existing target files.
    """
    target = Path(target_dir).resolve() if target_dir is not None else get_canonical_app_data_dir()
    target.mkdir(parents=True, exist_ok=True)

    candidates = list(extra_candidates or [])
    if extra_candidates is None:
        candidates.extend(_legacy_candidate_dirs())

    migrated: list[str] = []
    for src_dir in candidates:
        if not src_dir.is_dir() or src_dir == target:
            continue
        for item in src_dir.iterdir():
            dest = target / item.name
            if dest.exists():
                continue
            try:
                if item.is_file():
                    shutil.copy2(item, dest)
                    migrated.append(f"file: {item.name}")
                elif item.is_dir():
                    shutil.copytree(item, dest)
                    migrated.append(f"dir: {item.name}")
            except Exception as exc:
                LOGGER.warning("Legacy migration failed for %s: %s", item, exc)
    return migrated
