# S1 manual checklist: window behaviour

Covers the S1 tests that need real hardware. Automated coverage: `uv run pytest` (layout, settings, panel API) and `uv run pytest -m desktop` (real AppBar docking on the current monitor).

Run the app with `uv run inspectors-notebook`. Record the Windows build, monitor layout and scaling for each run.

## One monitor

- [ ] Starts docked on the right, 8 px in from the top, bottom and right edges; maximised windows shrink to make room.
- [ ] ↔ moves the panel to the left edge; maximised windows move over. Restarting keeps the left side.
- [ ] Collapse shrinks to the 64 px rail and the reserved strip shrinks with it; expand restores the previous width.
- [ ] Side switch and theme toggle work from the rail.
- [ ] Dragging the inner edge resizes between 320 and 640 px; the width is kept after restart.
- [ ] With the resize handle focused, the arrow keys widen and narrow the panel.
- [ ] Theme toggle switches dark and light; the window border colour follows.
- [ ] Rounded corners show on Windows 11; square corners on Windows 10 with nothing broken.
- [ ] Taskbar on the left, top and right: the panel never overlaps it.
- [ ] A full-screen app (F11 in a browser, a video) covers the panel; the panel comes back on top afterwards.
- [ ] Closing the window (taskbar, Alt+F4) releases the reserved strip.

## Two monitors

- [ ] Panel docks to the primary monitor; windows on the second monitor are unaffected.
- [ ] Unplugging the panel's monitor moves the panel to the remaining one and re-docks.
- [ ] Changing resolution or scaling re-docks at the right size.

## Mixed DPI

Primary at 100 %, second at 150 % or more (and the other way round).

- [ ] Panel width and inset are correct in logical pixels at each scaling; text is sharp, not bitmap-stretched.
- [ ] Changing the panel monitor's scaling while running re-docks at the new size.

## Sleep and resume

- [ ] Sleep with the panel docked, resume: the panel is still docked and the strip still reserved.
- [ ] Sleep, change monitor layout (undock a laptop), resume: the panel re-docks on the remaining screen.
