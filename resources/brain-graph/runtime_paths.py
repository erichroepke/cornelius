from __future__ import annotations

import os
from pathlib import Path


HOME = Path.home()
SETTINGS_PATH = Path(__file__).resolve().parents[2] / ".claude" / "settings.md"
NIKLAS_ROOT = HOME / "Desktop" / "Niklas"
STUDIO_BRAIN_LINK = NIKLAS_ROOT / "Studio" / "Brain"


def _load_settings() -> dict[str, str]:
    values: dict[str, str] = {}
    if not SETTINGS_PATH.exists():
        return values
    for raw in SETTINGS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _candidate_roots() -> list[Path]:
    settings = _load_settings()
    settings_root = settings.get("VAULT_BASE_PATH")
    candidates = []
    if settings_root:
        candidates.append(Path(settings_root).expanduser())
    candidates.extend(
        [
            NIKLAS_ROOT / "01-Brain",
            NIKLAS_ROOT / "Brain",
            STUDIO_BRAIN_LINK,
            HOME / "Desktop" / "Brain",
            HOME / "Desktop" / "Brain-replica",
            HOME / "Desktop" / "NIKLAS",
        ]
    )
    return candidates


def detect_brain_root(*env_keys: str, required_child: str = "wiki") -> Path:
    for key in env_keys:
        raw = os.environ.get(key)
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.exists() and (required_child is None or (candidate / required_child).exists()):
            return candidate
        return candidate

    for candidate in _candidate_roots():
        if candidate.exists() and candidate.is_dir():
            if required_child is None or (candidate / required_child).exists():
                return candidate.resolve() if candidate.is_symlink() else candidate

    fallback = _candidate_roots()[0]
    return fallback.resolve() if fallback.is_symlink() else fallback
