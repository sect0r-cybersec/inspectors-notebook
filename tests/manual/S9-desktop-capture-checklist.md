# S9 manual checklist: desktop capture

Automated coverage: `uv run pytest` (the allow list, recording gate, Inspector's own window, the UI Automation to OCR fallback, new-line detection, the size cap, and desktop events through the rules, timeline and export) and `uv run pytest -m desktop` (UI Automation reading a real console window exactly, and Windows OCR reading clear text). This list is the S9 exit test: text accuracy on real sessions in the lab.

Set up: Settings, **Desktop apps**: switch on **Capture text from these apps**, then allow Windows Terminal and Remote Desktop Connection (`mstsc.exe`) from the list of open apps. Start a case with an entity you will see on screen, such as a lab host name.

## Terminal (UI Automation)

- [ ] Run `whoami`, `hostname` and `ipconfig` in Windows Terminal. Each command's output appears once in the timeline, exactly as on screen, labelled `WindowsTerminal.exe`.
- [ ] Output naming the case entity is kept with the entity-match reason.
- [ ] Switching between two terminal windows adds a window event each time; running commands in one does not.
- [ ] PowerShell 7, cmd and WSL tabs all read.

## Remote desktop (OCR)

- [ ] RDP to a lab VM. The window event shows the host in its title (`lab-dc01 - Remote Desktop Connection`).
- [ ] Open Event Viewer or a command prompt in the session. Its text appears labelled `mstsc.exe (OCR, approximate)`.
- [ ] Record what OCR gets wrong, especially IPs, host names, hashes and paths:

| Screen | On screen | OCR read | Right? |
| --- | --- | --- | --- |
| | | | |

## Privacy

- [ ] With desktop capture off, or no case recording, nothing from desktop apps appears.
- [ ] Apps not on the allow list are never read, even in front.
- [ ] A minimised window is not read.

## Packaged build

- [ ] The same terminal check in the installed app (from the installer), which has not been tested with desktop capture yet.
