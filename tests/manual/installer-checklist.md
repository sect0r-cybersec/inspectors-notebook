# Installer manual checklist

Automated coverage: `uv run pytest -m installer` after `packaging/build.ps1` (installs for the current user, checks the files and the browser registration, starts the installed app through the installed relay, checks a second launch, upgrades over a running app, uninstalls and checks everything is removed but the cases). CI runs it on a Windows Server runner. This list covers what needs a person and a clean machine.

Use the installer from CI (the `installer` artifact on the run) or from `dist\` after a local build.

## Fresh Windows 10 and Windows 11 virtual machines

Run this list on each. Neither machine should have Python, uv or Node.js installed.

- [ ] The installer runs without a UAC prompt. SmartScreen warns because the installer is not signed yet: **More info**, then **Run anyway**.
- [ ] It installs to `%LOCALAPPDATA%\Programs\InspectorsNotebook` and adds **Inspector's Notebook** to the Start menu; the desktop shortcut appears only if ticked.
- [ ] **Launch Inspector's Notebook** at the end starts the panel, docked to the right.
- [ ] Load the extension (Developer mode, Load unpacked, `extension/src`). The popup says the app is connected; close the panel and **Open Inspector** starts it again.
- [ ] Start a case, run a query in the lab, export it. Screenshots are saved (WebP), which shows the image libraries were bundled.
- [ ] Turn on Start Inspector when Windows starts, sign out and back in: Inspector starts.
- [ ] **Settings, Apps** lists Inspector's Notebook with its version and icon.

## Upgrade

- [ ] With the panel open and a browser connected, run the installer again. It offers to close Inspector, replaces it, and the extension reconnects.

## Uninstall

- [ ] Uninstall from **Settings, Apps**. It asks whether to delete saved cases and settings; **No** keeps `%LOCALAPPDATA%\InspectorsNotebook\cases`.
- [ ] Uninstall again after reinstalling and answer **Yes**: both `%LOCALAPPDATA%\InspectorsNotebook` and `%APPDATA%\InspectorsNotebook` are gone.
- [ ] The extension popup no longer reaches the app, and the install folder, Start menu entry and Start with Windows entry are gone.

## Work laptop (optional)

- [ ] Your EDR or application control lets the unsigned installer and app run, or record what it blocks. This decides how soon code signing (NFR-12) is needed.
