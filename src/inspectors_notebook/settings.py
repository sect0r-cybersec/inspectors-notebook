"""Settings, stored as JSON in the user's roaming profile.

Values from the file and from the settings screen go through the same checks; anything
missing or invalid keeps its current value (the default, on load).
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from .geometry import DEFAULT_WIDTH, MAX_WIDTH, MIN_WIDTH, DockMode, Side

log = logging.getLogger(__name__)

Theme = Literal["dark", "light", "system"]


@dataclass
class Settings:
    # Window (FR-48 to FR-52)
    side: Side = "right"
    theme: Theme = "dark"
    width: int = DEFAULT_WIDTH
    dock: DockMode = "appbar"
    start_with_windows: bool = False  # FR-38
    # Starting cases (FR-3, FR-6)
    suggest_cases: bool = True
    dwell_seconds: int = 30
    preroll_minutes: int = 3
    # Screenshots (FR-13); interval 0 means off
    screenshots: bool = True
    interval_seconds: int = 0
    # Case cache (FR-29, FR-32)
    cache_size: int = 5
    warn_unexported: bool = True
    # Times and exports (docs/decisions.md)
    show_utc: bool = False
    export_rows: int = 5


CHOICES = {"side": ("left", "right"), "theme": ("dark", "light", "system"), "dock": ("appbar", "float")}
RANGES = {
    "width": (MIN_WIDTH, MAX_WIDTH),
    "dwell_seconds": (5, 600),
    "preroll_minutes": (1, 30),
    "interval_seconds": (0, 3600),
    "cache_size": (1, 50),
    "export_rows": (0, 50),
}
INTERVAL_MIN = 15  # an interval below this is too frequent to be useful


def changed(settings: Settings, changes: dict) -> Settings:
    """A copy with every valid change applied; invalid ones are ignored."""
    valid = {}
    for name, value in changes.items():
        if name not in Settings.__dataclass_fields__:
            continue
        current = getattr(settings, name)
        if name in CHOICES:
            if value in CHOICES[name]:
                valid[name] = value
        elif isinstance(current, bool):
            if isinstance(value, bool):
                valid[name] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            low, high = RANGES[name]
            value = max(low, min(high, value))
            if name == "interval_seconds" and 0 < value < INTERVAL_MIN:
                value = INTERVAL_MIN
            valid[name] = value
    return replace(settings, **valid)


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
    return changed(Settings(), raw) if isinstance(raw, dict) else Settings()


def save(settings: Settings, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, path)
