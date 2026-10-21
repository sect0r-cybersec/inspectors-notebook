# Decisions

Changes to the original requirements, and decisions made during the build. Newest first. Each entry says what changed, why, and which requirements it affects.

## 21 October 2026

### No encrypted case store

Cases are stored as plain files in the user's Windows profile (`%LOCALAPPDATA%\InspectorsNotebook\cases`). Inspector's Notebook keeps SOC investigation notes, not chain-of-custody evidence, so per-case encryption is out of scope.

- Drops FR-33 (per-case keys, destroyed on deletion) and the DPAPI-protected keys in NFR-5.
- Deleting a case deletes its files. On SSDs, deleted data may remain recoverable until overwritten.
- The files are protected by the user's Windows account permissions, and by BitLocker where it is enabled.
- The S4 exit test "deleting a case destroys its key" becomes "deleting a case removes its files".

### No hashing of captures or screenshots

The proposed "light integrity" decision (a SHA-256 hash per capture, NFR-6) is not adopted. The tool supplements an analyst's notes; it is not an evidence system.

### Local timestamps, UTC optional

Captures are stamped in local time with the UTC offset, for example `2026-10-21T10:05:00.123+01:00`. The panel and exports show local time; showing UTC alongside is an optional setting (with the timeline display, S5). Changes FR-15, which specified UTC.

### Screenshots taken by the companion

Browsers only let an extension capture tabs if it may read every website, which would break NFR-8. The extension asks, and the companion captures the browser window and saves WebP (Pillow). The mechanism changes; FR-13's triggers do not.

### Browser extension only for the initial product

A standalone mode without the extension (window titles, UI Automation, clipboard) was considered for machines that block extensions. Not in the initial product; it may be added later, sharing the S9 desktop capture work.

### S3 exit items deferred

The lab has no incidents yet, so S3 moved on without incident and alert URL patterns (FR-2) or the 20-query check. Until the patterns exist, start detection (FR-3) cannot recognise real incident pages; cases are started manually. See `tests/manual/S3-lab-capture-guide.md`.

### Companion written in Python with pywebview

The proposed decision is confirmed.
