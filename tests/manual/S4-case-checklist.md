# S4 manual checklist: cases

Covers what the automated tests cannot: the panel controls in the real app, with real consoles. Automated coverage: `uv run pytest` (every rule, the case lifecycle, the store, and `tests/test_investigation.py`, a scripted investigation built from lab captures).

Run the app with `uv run inspectors-notebook`, with the extension loaded and your lab consoles open.

## Starting and stopping

- [ ] **Start manually** opens the form; Cancel closes it without starting anything.
- [ ] Starting with an incident ID, a title and two entities shows the red recording strip, the case header and both entity chips.
- [ ] The timer counts up; **Pause** stops it and greys the strip; **Resume** carries on from the same time.
- [ ] Nothing is added to the case while it is paused.
- [ ] **Stop** returns the panel to the idle view. The case folder appears under `%LOCALAPPDATA%\InspectorsNotebook\cases`.
- [ ] Starting again with the same incident ID resumes the same case with its earlier events.
- [ ] The rail shows the recording dot and timer when collapsed.

## Capture into a case

- [ ] In Defender advanced hunting, a query and its results raise the kept count. Running the identical query again raises the hidden count (duplicate).
- [ ] Visiting the incident or alert list raises the hidden count (navigation only).
- [ ] A query whose results mention a case entity is kept even when it would otherwise be hidden.
- [ ] **Seen in results** offers IPs, domains and files before hashes; **+** makes one a case entity.
- [ ] **+ Entity** adds a typed value; Enter adds it, Escape cancels; typing is not interrupted while queries run.
- [ ] Removing an entity chip changes the counts back where it mattered.
- [ ] Screenshots appear in the case's `screenshots` folder while recording, and none while paused or idle.

## Not testable yet

Start suggestions ("Incident detected"), switching incidents mid-case, and incident IDs from URLs need the incident URL patterns from a lab incident (see `tests/manual/S3-lab-capture-guide.md`). The logic is covered by `tests/test_cases.py` and `tests/test_investigation.py`.
