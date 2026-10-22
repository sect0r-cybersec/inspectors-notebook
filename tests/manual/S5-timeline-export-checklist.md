# S5 manual checklist: timeline, export, cases and settings

Automated coverage: `uv run pytest` (timeline items, exports against golden files in all three formats, the case cache rules, settings validation, the panel API), `uv run pytest -m desktop` (clipboard, global shortcuts, window capture, docking), and `cd extension && npm test` (including interval screenshots). This list covers what needs a person.

## Timeline

- [ ] Timeline, Findings, Review and Hidden tabs show the right items, newest first, with counts.
- [ ] All shows every item whatever its decision. **Show** narrows any tab to one event type, listing only the types in the case; the tab counts follow it, a capture arriving does not reset it, and a new case starts on All event types (FR-23).
- [ ] At the narrowest width (320 px) each tab's count sits under its label and all five tabs fit; from the default 400 px they sit on one line.
- [ ] The star marks a finding; the item turns amber and appears under Findings.
- [ ] Comment: Enter saves, Escape cancels; typing is not interrupted while captures arrive.
- [ ] Hide moves an item to Hidden; Restore brings it back.
- [ ] The tag button opens the 15 ATT&CK v20 tactics with the item's tags ticked; Save shows them as chips under the item, Cancel or Escape leaves them as they were, and a capture arriving while the list is open does not close it.
- [ ] In Review, Keep and Hide decide the item, and **+ value** adds it as a case entity.
- [ ] A screenshot item's pin includes it in the export and the zip.
- [ ] The note box adds a timestamped note.

## Export

- [ ] Paste the plain text and Markdown into your ticketing system; they read cleanly.
- [ ] Paste the HTML into a rich-text ticket editor or email; it arrives formatted, not as tags.
- [ ] Save as file writes `.txt`, `.md` or `.html` where you choose.
- [ ] Screenshots (.zip) contains the pinned screenshots, named like their timeline entries.
- [ ] After copying or saving, the case shows as Exported on the Cases screen.
- [ ] With Show UTC on, times read `13:08 (12:08 UTC)` in the panel and the export.
- [ ] Tagged items show `ATT&CK: Lateral Movement (TA0008)` in every format, findings show their tactics in brackets, and the header lists the case's tactics in matrix order.

## Cases

- [ ] With more cases than the limit, the oldest exported case is deleted when a new case starts.
- [ ] An unexported old case is listed for confirmation instead; Keep pins it, Delete removes it.
- [ ] Pinned cases and the recording case are never deleted; "Deleted when the next case starts" marks the right one.
- [ ] Open makes a past case the recording one again.

## Settings

- [ ] Theme, side and Reserve screen space take effect at once and survive a restart.
- [ ] Start Inspector when Windows starts: sign out and back in; Inspector starts.
- [ ] Turning off key-event screenshots stops them; Also every 60 sec adds interval screenshots while recording.
- [ ] Shortcuts lists any combination another program holds on your machine.

## Shortcuts

- [ ] From any window: Ctrl+Alt+N focuses the note box (or opens the start form with no case), Ctrl+Alt+S pauses and resumes, Ctrl+Alt+I collapses and expands.

## Gate 1

The spec's exit for phase 1: a week of real cases where the timeline needs no manual fixing.
