import pytest

from inspectors_notebook.geometry import (
    INSET,
    MAX_WIDTH,
    MIN_WIDTH,
    Rect,
    clamp_width,
    edge_strip,
    panel_rect,
    restore_width,
    strip_width,
    to_physical,
)

PRIMARY = Rect(0, 0, 1920, 1080)
# A 4K monitor at 150 % sitting to the left of the primary, so its x coordinates are negative.
LEFT_4K = Rect(-3840, -200, 0, 1960)


@pytest.mark.parametrize(
    ("dpi", "expected"),
    [(96, 400), (120, 500), (144, 600), (168, 700), (192, 800)],
)
def test_to_physical_scales_by_dpi(dpi, expected):
    assert to_physical(400, dpi) == expected


def test_strip_width_includes_inset_on_both_sides():
    assert strip_width(400, 96) == 400 + 2 * INSET
    assert strip_width(400, 144) == round((400 + 2 * INSET) * 1.5)


@pytest.mark.parametrize("monitor", [PRIMARY, LEFT_4K])
def test_edge_strip_right(monitor):
    s = edge_strip(monitor, "right", 416)
    assert (s.right, s.width, s.top, s.bottom) == (monitor.right, 416, monitor.top, monitor.bottom)


@pytest.mark.parametrize("monitor", [PRIMARY, LEFT_4K])
def test_edge_strip_left(monitor):
    s = edge_strip(monitor, "left", 416)
    assert (s.left, s.width, s.top, s.bottom) == (monitor.left, 416, monitor.top, monitor.bottom)


def test_restore_width_keeps_shell_chosen_outer_edge():
    # Another AppBar already holds 100 px on the right, so the shell pushed us inwards
    # and shrank the strip to what was left.
    proposed = Rect(1404, 0, 1820, 1080)
    assert restore_width(proposed, "right", 416) == Rect(1404, 0, 1820, 1080)
    squeezed = Rect(1600, 0, 1820, 1080)
    assert restore_width(squeezed, "right", 416) == Rect(1404, 0, 1820, 1080)
    assert restore_width(Rect(100, 0, 300, 1080), "left", 416) == Rect(100, 0, 516, 1080)


def test_panel_rect_insets_and_avoids_bottom_taskbar():
    strip = Rect(1504, 0, 1920, 1080)
    work = Rect(0, 0, 1504, 1032)  # taskbar 48 px at the bottom; our strip already reserved
    assert panel_rect(strip, work, 8) == Rect(1512, 8, 1912, 1024)


def test_panel_rect_avoids_top_taskbar_on_negative_monitor():
    strip = edge_strip(LEFT_4K, "left", 624)
    work = Rect(-3216, -128, 0, 1960)  # taskbar 72 px at the top
    assert panel_rect(strip, work, 12) == Rect(-3828, -116, -3228, 1948)


@pytest.mark.parametrize(
    ("given", "expected"),
    [(0, MIN_WIDTH), (MIN_WIDTH - 1, MIN_WIDTH), (400, 400), (10_000, MAX_WIDTH), (450.7, 450)],
)
def test_clamp_width(given, expected):
    assert clamp_width(given) == expected
