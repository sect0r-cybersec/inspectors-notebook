"""Panel layout maths. Pure functions, so they test on any OS.

Two units appear here: logical pixels (CSS pixels, what the settings and the UI use)
and physical pixels (what Win32 uses once the process is per-monitor DPI aware).
"""

from dataclasses import dataclass
from typing import Literal

Side = Literal["left", "right"]
DockMode = Literal["appbar", "float"]

DEFAULT_WIDTH = 400
MIN_WIDTH = 320
MAX_WIDTH = 640
RAIL_WIDTH = 64
# Gap between the panel and the screen edge, so the rounded corners show (FR-52).
INSET = 8


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True)
class Layout:
    side: Side
    width: int  # logical px, panel only (no inset)
    mode: DockMode


def clamp_width(width: int) -> int:
    return max(MIN_WIDTH, min(MAX_WIDTH, int(width)))


def to_physical(logical: int, dpi: int) -> int:
    return round(logical * dpi / 96)


def strip_width(panel_width: int, dpi: int) -> int:
    """Physical width of the strip reserved at the edge: the panel plus an inset each side."""
    return to_physical(panel_width + 2 * INSET, dpi)


def edge_strip(area: Rect, side: Side, width: int) -> Rect:
    """A strip of `width` physical px along one side of `area`."""
    if side == "right":
        return Rect(area.right - width, area.top, area.right, area.bottom)
    return Rect(area.left, area.top, area.left + width, area.bottom)


def restore_width(proposed: Rect, side: Side, width: int) -> Rect:
    """Re-apply our width after the shell has moved the strip (ABM_QUERYPOS).

    The shell may push the strip inwards, for example when another AppBar already
    holds that edge. It keeps the outer edge it chose; the inner edge is ours.
    """
    if side == "right":
        return Rect(proposed.right - width, proposed.top, proposed.right, proposed.bottom)
    return Rect(proposed.left, proposed.top, proposed.left + width, proposed.bottom)


def panel_rect(strip: Rect, work: Rect, inset: int) -> Rect:
    """Where the panel window sits inside its strip.

    Vertical bounds come from the monitor's work area so the panel never runs
    under a taskbar at the top or bottom of the screen.
    """
    top = max(strip.top, work.top) + inset
    bottom = min(strip.bottom, work.bottom) - inset
    return Rect(strip.left + inset, top, strip.right - inset, bottom)
