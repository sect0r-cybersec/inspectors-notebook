# Decisions

Changes to the original requirements, and decisions made during the build. Newest first. Each entry says what changed, why, and which requirements it affects.

## 21 October 2026

### S6 processing queue

- **The queue is built before the model.** The labelling queue (newest first, one worker, 200-job cap, replaced jobs for changed events) is in place and tested with a stand-in model. The app runs without a labeller until S7, so nothing is labelled yet and the footer's "Labelling N events" only appears once the model is in.
- **Repeated page captures merge by capture time** (FR-42): the same URL in the same tab within 2 s of the previous capture joins it. The time comes from the extension's timestamp, so events replayed from the pre-roll merge the same way. A newer title replaces the old one and is kept when the case is reopened.
- **The panel refreshes at most five times a second** during a burst, instead of once per event. Before this, a burst of 1,000 events took 60 s to reach the panel, because each one waited for a full redraw; now it takes 2.5 s and the panel's UI thread answers within 4 ms throughout. The S6 exit test was "never freezes the panel"; this was the freeze.
- **Order comes from arrival, per browser.** Each browser's events arrive in capture order over its own pipe connection and are stored in that order; sequence numbers and timestamps (FR-39) are already stamped by the extension.

### Installer

- **PyInstaller in folder mode**, not Nuitka: no C compiler is needed and it handles pywebview's .NET and WebView2 parts. The app, the relay and the register tool share one folder and one Python runtime (NFR-9).
- **Per user, no admin rights.** Inno Setup installs to `%LOCALAPPDATA%\Programs\InspectorsNotebook` with no UAC prompt, matching NFR-5 and the per-user browser registration. It needs Windows 10 1809 or later, the oldest release WebView2 supports.
- **Install registers the relay; uninstall removes the registration** and the Start with Windows entry. Upgrades close a running app and relay first.
- **Uninstalling asks before deleting cases and settings**, defaulting to keep. A silent uninstall keeps them.
- **Not code-signed yet.** There is no certificate, so Windows SmartScreen warns on first run and some EDR tools may block it. NFR-12 still applies before the first public release.
- **No model in the installer**: there is no model until S7, so first-run model download (NFR-9) comes with it.
- **Installer wording is Inno Setup's built-in English.** It has no British English translation; the strings shown on its pages use no American spellings.
- **Not tested on fresh Windows 10 and 11 virtual machines yet.** CI installs, runs, upgrades and uninstalls on a Windows Server runner; the fresh-VM check is in the installer checklist.

### S5 choices

- **Global shortcuts use Ctrl+Alt**: Ctrl+Alt+N adds a note, Ctrl+Alt+S starts or pauses recording, Ctrl+Alt+I shows or collapses the panel. The spec's Ctrl+Shift+N would take over Chrome's incognito window, Edge's InPrivate window and Firefox's reopen-closed-window while Inspector runs. Ctrl+Alt+R was planned for recording but another program held it on the development machine. A shortcut another program holds is reported in Settings rather than silently lost. Changes FR-25 and FR-53.
- **Findings are starred by the analyst** until the model's finding highlights exist (S7, MJ-3). Starred events lead the export's Key findings.
- **Export defaults**: up to 5 relevant rows per query, and interval screenshots every 60 seconds when switched on. Both are settings (the spec's open questions).
- **The installer is its own stage after S5**, not part of S5's exit tests.

### Incident detection works on any site; any site can be listened to

Start detection must not depend on test data for every SIEM, EDR and ticketing platform. Two changes:

- A generic recogniser finds incident, alert, case, ticket and detection pages from the URL alone: a record word followed by an ID (`/incidents/4821`, `/cases/123`, `incident.do?sys_id=...`, `/browse/SOC-123`), including inside `#` fragment routes. List pages are not records. Console-specific patterns, where known, take priority. Changes FR-2, which asked for per-console patterns.
- "Listen on this site" in the extension popup asks the browser for permission for the current HTTPS site only and adds it to the listened sites. Nothing beyond the shipped consoles is granted at install, so NFR-8 holds; this is its "the user adds others".

Added sites get page visits, incident detection, entity matching and screenshots. Exact query capture (query text, row counts, errors) still needs a console parser, so it covers Defender XDR and Sentinel only. This supersedes the deferred incident URL patterns below.


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
