<div align="center">

![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Python](https://img.shields.io/badge/python-3.13-3776AB)
![Platform](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6)
![Status](https://img.shields.io/badge/status-early%20development-orange)

# Inspector's Notebook

A local flight recorder for SOC investigations.

</div>

Inspector's Notebook records what you do in security consoles during an investigation and will hand back a timestamped timeline ready to paste into a ticket. It is built for a single analyst on their own Windows machine: a listener extension in Chrome, Edge or Firefox feeds a desktop panel docked to the edge of your screen. Everything stays on your machine.

<p align="center">
  <img src="assets/mockup-live-case.png" alt="The Inspector's Notebook panel recording a case: incident header, entity chips, and a timeline of queries, notes and a highlighted finding" width="420">
</p>

> **Status:** early development. Phase 1 is built: the docked panel, the browser connection, Defender XDR and Sentinel query capture, cases, the timeline, notes and export. A per-user Windows installer is built and tested in CI. The local decision model comes next.

## Features

**Available now**

- **A panel that stays out of the way.** Docks to the right or left screen edge and other windows make room for it. Collapse it to a 64 px rail, switch sides in one click, drag to resize, and pick a dark or light theme.
- **Always listening, never recording without you.** The extension watches Defender XDR and Azure portal tabs, but nothing is captured unless the app is open.
- **One click to start.** Open Inspector from the browser's toolbar popup and the app starts and connects.
- **Works on any site you choose.** Inspector recognises incident, alert, case and ticket pages from their URL on any platform, and suggests starting a case when you dwell on one and start investigating. Defender XDR and Sentinel are listened to out of the box; add your SIEM, EDR or ticketing system with **Listen on this site** in the extension popup.
- **Queries captured as you run them.** Advanced hunting in Defender XDR and Logs in Sentinel: the exact KQL, the row count, the columns, and the error if it fails. Entities such as IPs, hashes and files are picked out of the results.
- **Cases that sort themselves.** Start a case, add the hosts, users and IPs you care about, and every capture is kept, sent for review or hidden: anything that mentions a case entity is always kept, while duplicates, list pages, events from another tenant and anything captured while you were away are set aside. Nothing is deleted; hidden events can be restored.
- **A timeline you can trust.** Newest first, with Timeline, Findings, Review and Hidden tabs. Star findings, comment on events, add notes, keep or hide anything in one click.
- **Exports ready for the ticket.** Plain text, Markdown or HTML, copied or saved, with your findings first, each query's text, a summary line built from the data and the rows that name your entities. Pinned screenshots go in a zip named after their timeline entries.
- **A tidy case cache.** The last five cases are kept; older ones are removed, never the one you are working on or ones you pinned, and Inspector asks before removing a case you never exported.
- **Keyboard shortcuts from anywhere.** Ctrl+Alt+N adds a note, Ctrl+Alt+S starts or pauses a case, Ctrl+Alt+I shows or collapses the panel.
- **Per-tab pause.** Stop capture in any console tab from the popup.
- **Local only.** The browser and the app talk over a pipe only your Windows account can open. Nothing listens on a network port.

**Planned**

- A local decision model that labels events, highlights findings and decides borderline events.

## Quick start

### With the installer

You need Windows 10 (1809 or later) or 11. There is no published release yet: take `InspectorsNotebook-<version>-setup.exe` from the `installer` artifact of a CI run, or build it yourself (see [For developers](#for-developers)).

Run it. It installs for your Windows account only, so it needs no admin rights, and registers the relay with Chrome, Edge and Firefox. The installer is not code-signed yet, so SmartScreen warns on first run: choose **More info**, then **Run anyway**. Then load the extension as described below, and start Inspector from the Start menu or the extension's popup.

Uninstall from **Settings, Apps**. It asks before deleting your saved cases and settings.

### From source

You also need [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org/). From the repository folder:

```bash
uv sync
uv run inspectors-notebook-register install
cd extension && npm install
```

The second command lets Chrome, Edge and Firefox start the app's relay. It writes to your user registry only, so no admin rights are needed.

### Loading the extension

Until the extension is in the browser stores, load it from `extension/src`:

- **Chrome or Edge:** open `chrome://extensions` or `edge://extensions`, turn on Developer mode, choose **Load unpacked** and pick `extension/src`.
- **Firefox:** open `about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on** and pick `extension/src/manifest.json`. Firefox removes temporary add-ons when it restarts.

Restart any browser that was already open.

## Usage

Start the panel from the Start menu, with `uv run inspectors-notebook` from source, or click **Open Inspector** in the extension's toolbar popup. The panel docks to the screen edge and its status strip shows what the extension can see, for example `Extension listening in 2 tabs`. Close the panel from the taskbar or with Alt+F4.

To remove the browser registration of a from-source install:

```bash
uv run inspectors-notebook-register uninstall
```

The registration points at this folder's `.venv`, so run `install` again if you move the repository.

## Documentation

- [Window behaviour checklist](tests/manual/S1-window-checklist.md): docking, multiple monitors, mixed scaling and sleep.
- [Relay and extension checklist](tests/manual/S2-relay-checklist.md): the browser connection end to end.
- [Lab capture guide](tests/manual/S3-lab-capture-guide.md): what to capture in the lab to finish the console parsers.
- [Cases checklist](tests/manual/S4-case-checklist.md): starting, pausing and stopping cases in the real app.
- [Timeline and export checklist](tests/manual/S5-timeline-export-checklist.md): the timeline, exports, the case cache, settings and shortcuts.
- [Installer checklist](tests/manual/installer-checklist.md): installing, upgrading and uninstalling on fresh Windows 10 and 11 machines.
- [Decisions](docs/decisions.md): where the build departs from the original requirements, and why.

## For developers

The project is built in stages, each finished with passing tests before the next starts. Stages 1 (panel) and 2 (relay and extension) are complete. Stage 3 (console parsers) captures Defender XDR and Sentinel queries; reading incident IDs from URLs needs a lab incident to capture. Stage 4 (cases and rules) and stage 5 (timeline, export, case cache, settings) are built, followed by the installer. Decisions that changed the original requirements are in [docs/decisions.md](docs/decisions.md).

| Path | What it holds |
| --- | --- |
| `src/inspectors_notebook/` | Companion app: panel, AppBar docking, pipe, relay, browser registration |
| `extension/src/` | Listener extension, one Manifest V3 codebase for all three browsers |
| `extension/src/parsers/` | One versioned module per console |
| `packaging/` | PyInstaller build, Inno Setup script and the build script |
| `tests/` | Python unit and integration tests, plus manual checklists |
| `extension/tests/` | Browser round-trip tests |

Run the tests:

```bash
uv run pytest                  # unit and pipe tests
uv run pytest -m desktop       # real docking and window capture; uses the desktop while it runs
uv run pytest -m installer     # installs the built installer for you, then uninstalls it
cd extension
npm run test:unit              # parser framework, request hook, entities
npm test                       # Chrome and Edge
npm run test:firefox           # Firefox
npm run lint                   # web-ext lint
```

Build the installer with Inno Setup 6 installed (`winget install JRSoftware.InnoSetup`):

```bash
powershell -ExecutionPolicy Bypass -File packaging/build.ps1
```

It writes the app folder to `dist/InspectorsNotebook` and the installer next to it. The installer tests put your own browser registration and Start with Windows entry back when they finish.

The browser tests need the relay registered and the app closed. They serve console pages locally, so they never reach the real consoles.

Two rules apply to every change: all inference runs locally and captured data never leaves the machine, and test fixtures come from a purple team lab, never from real client data.

## Licence

Not chosen yet.
