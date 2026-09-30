"""JSON speichern, sichern und nach einem Pull wiederherstellen."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from .constants import BACKUP_KEEP


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def backup_dir_for(path: Path) -> Path:
    return path.parent / "backups"


def _hours_backup_files(path: Path) -> list[Path]:
    folder = backup_dir_for(path)
    if not folder.exists():
        return []
    return sorted(
        folder.glob(f"{path.stem}-*{path.suffix}"),
        key=lambda item: (item.stat().st_mtime_ns, item.name),
    )


def prune_backup_folder(path: Path, keep: int = BACKUP_KEEP) -> None:
    folder = backup_dir_for(path)
    if not folder.exists():
        return
    for leftover_pdf in folder.glob("*.pdf"):
        leftover_pdf.unlink(missing_ok=True)
    old = _hours_backup_files(path)
    for leftover in old[:-keep]:
        leftover.unlink(missing_ok=True)


def backup_existing(path: Path, keep: int = BACKUP_KEEP) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    folder = backup_dir_for(path)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = folder / f"{path.stem}-{stamp}{path.suffix}"
    index = 1
    while dest.exists():
        dest = folder / f"{path.stem}-{stamp}-{index}{path.suffix}"
        index += 1
    shutil.copy2(path, dest)
    prune_backup_folder(path, keep=keep)
    return dest if dest.exists() else None


def list_hours_backups(path: Path, keep: int = BACKUP_KEEP) -> list[Path]:
    return _hours_backup_files(path)[-keep:]


def latest_backup(path: Path) -> Path | None:
    matches = list_hours_backups(path)
    return matches[-1] if matches else None


def backup_stamp(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M")


def read_json_object(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def load_hours_payload(json_path: Path) -> tuple[dict, str]:
    main = read_json_object(json_path) if json_path.exists() else None
    backup_path = latest_backup(json_path)
    backup = read_json_object(backup_path) if backup_path else None
    main_days = (main or {}).get("days") or {}
    backup_days = (backup or {}).get("days") or {}
    if main and main_days:
        return main, "file"
    if backup and backup_days:
        merged = dict(backup)
        if main and main.get("current") and not merged.get("current"):
            merged["current"] = main["current"]
        return merged, "backup"
    if main:
        return main, "file"
    return {"current": None, "days": {}}, "empty"
