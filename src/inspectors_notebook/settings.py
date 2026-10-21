"""Panel settings, stored as JSON in the user's roaming profile."""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .geometry import DEFAULT_WIDTH, DockMode, Side, clamp_width

log = logging.getLogger(__name__)

Theme = Literal["dark", "light", "system"]

_SIDES = ("left", "right")
_THEMES = ("dark", "light", "system")
_DOCK_MODES = ("appbar", "float")


@dataclass
class Settings:
    side: Side = "right"
    theme: Theme = "dark"
    width: int = DEFAULT_WIDTH
    dock: DockMode = "appbar"


def default_path() -> Path:
    return Path(os.environ["APPDATA"]) / "InspectorsNotebook" / "settings.json"


def load(path: Path) -> Settings:
    """Read settings, falling back to the default for anything missing or invalid."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))  # tolerate a BOM from hand edits
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as e:
        log.warning("Ignoring unreadable settings file %s: %s", path, e)
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    s = Settings()
    if raw.get("side") in _SIDES:
        s.side = raw["side"]
    if raw.get("theme") in _THEMES:
        s.theme = raw["theme"]
    if raw.get("dock") in _DOCK_MODES:
        s.dock = raw["dock"]
    width = raw.get("width")
    if isinstance(width, int) and not isinstance(width, bool):
        s.width = clamp_width(width)
    return s


def save(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, path)
