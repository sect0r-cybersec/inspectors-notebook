# Decisions

Changes to the original requirements, and decisions made during the build. Newest first. Each entry says what changed, why, and which requirements it affects.

## 22 October 2026

### S9: desktop capture

- **No new dependencies.** UI Automation comes from .NET Framework's managed client and OCR from Windows' own `Windows.Media.Ocr`, both reached through pythonnet, which pywebview already ships. Nothing is downloaded and nothing leaves the machine.
- **Any app, by the analyst's choice** (FR-45). Settings lists the programs with a window open; the analyst allows them by program name (such as `WindowsTerminal.exe` or `mstsc.exe`). No per-app rules. Off by default, with no apps allowed.
- **Only the window in front, only while a case is recording.** Desktop text never goes into the pre-roll buffer, unlike browser events: what is on screen in a terminal or remote desktop is too broad to keep before the analyst has started a case.
- **UI Automation first, OCR as the fallback** (FR-46). UI Automation reads the text on screen exactly. OCR reads RDP and VDI windows, which are pixels only, and is marked "OCR, approximate" in the timeline and export. Measured on a Windows Terminal window: UI Automation read `user jdoe on HOST-12 from 10.0.4.17` exactly; OCR dropped the IP at 1x, 2x and 3x scale and garbled it at 1.5x (`HOST?12 from 1@.@.4.17`). Entity matching on OCR text will miss what OCR misreads.
- **Only new lines are sent.** Each look (every 3 seconds) sends the lines not on screen before, ignoring lines within OCR jitter of one already seen, so a repeated identical line is not sent twice. Switching to an allowed window is its own event; a title change is not, because terminals put each running command in the title.
- **The same rules as browser events** (FR-47): text naming a case entity is kept as an entity match, idle-time text is hidden, and the model jobs see it in the eval set.
- **Not checked yet**: RDP sessions and thick clients in the lab (the S9 exit test), and desktop capture in the packaged build (the installer's frozen app).

### S8: site-agnostic capture instead of Elastic and Falcon parsers

Inspector is meant for any SIEM, EDR and ticketing system, not a list of named ones, and per-platform parsers need lab data from each platform. S8 builds the generic route instead; console parsers stay as the precise path where someone contributes one.

- **Generic query capture on added sites** (`extension/src/parsers/generic.js`). On any site added with "Listen on this site" that has no console parser, a POST or PUT whose body holds a query-like field (`query`, `queryString`, `q`, `search`, `esql`, `kql`, `sql`, `spl` and similar) whose text reads like a query (a pipe, a query keyword, or a field compared with a value) is captured as a query. Results are read from common shapes: named columns with rows or values, a list of tables, search hits, or a list of records. Errors from `error` or `errors`. Plain words (a name lookup), GraphQL and anything unreadable are left alone: the page visit, incident detection and screenshots still happen. Replaces the planned Elastic and Falcon parsers (changes S8 and FR-16).
- **Evidence**: the Defender and Sentinel lab captures read the same through generic capture as through their console parsers (same query text, row count, columns and entities). Elastic, LogScale, Splunk and other consoles are **UNTESTED**: their real request shapes have not been captured, and some (Kibana's internal search, which can stream compressed responses) may not be readable this way.
- **The request hook is registered on added sites at runtime** (`scripting` permission, added to the manifest). Tabs already open pick it up when they next load. Verified in Chrome and Edge; Firefox is **UNTESTED** because its test runner cannot drive pages.
- **Ticket triggers are generic too** (FR-3): opening a ticket, case or any record page on another listened site while on an incident suggests a case for that incident at once, without waiting for the dwell time. No per-ITSM rules, which settles the spec's open question on which ITSM to support first.

### S7 model findings (no model in the app yet)

Measured in a throwaway environment on 22 October 2026, CPU only, 4 threads standing in for a 16 GB, 4-core work laptop. strands-decider 0.2.0 and its 51 dependencies were checked first: no LiteLLM, and the PyPI wheel is attested to the `strands-labs/strands-decider` release workflow.

| | Full precision | int8, saved and reloaded |
| --- | --- | --- |
| Memory after load / peak | 7.7 GB / 8.0 GB | 3.1 GB / 4.4 GB |
| All five model jobs, median / p95 | 15.2 s / 16.8 s | 4.2 s / 4.4 s |
| MJ-5 only, median / p95 | 5.5 s / 6.8 s | 1.4 s / 1.7 s |

- **No light model exists.** The smallest decider is the 2B; the spec's 400M light tier for 8 GB laptops is not available.
- **Full precision misses NFR-3** (5 s p95) on 4 cores and takes half of a 16 GB laptop's memory. int8 meets it, but shifts answers (mean 0.085, up to 0.26 on yes/no scores; 4 of 12 choices changed), so int8 has to pass Gate 2 on its own.
- **Prompt injection moves the model**: log text saying "answer no" gave the lowest relevance score of the sample, on an event naming a case entity. Entity match always wins (FR-19), so it cannot hide that event.
- **The int8 checkpoint is converted once on a build machine** (18 GB peak) and must be hosted; it cannot be converted on a user's laptop.
- **torch, transformers and strands-decider are not project dependencies yet.** That waits for Gate 2.

### Gate 2 criteria (proposed)

The model (entity match always keeps; otherwise its relevance score keeps at 0.7 or above, hides at 0.3 or below, and sends the rest to review) passes Gate 2 on the lab eval set when, against plain entity matching:

- its F1 is higher (review counts as shown to the analyst),
- it loses no more relevant evidence (relevant items hidden), and
- it sends no more than 20% of items to review, since a model that sends everything uncertain to review saves the analyst nothing.

On a 19-item synthetic case (invented events, my labels), the int8 model scored F1 0.839 against entity matching's 0.818 and lost no evidence, but sent 37% of items to review, so it fails. That checks the tooling, not the model: Gate 2 needs your labelled lab cases (`tests/manual/S7-eval-labelling-guide.md`).

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
