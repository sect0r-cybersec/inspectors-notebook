# S2 manual checklist: relay and listener extension

Covers the S2 tests that need a real setup. Automated coverage:

- `uv run pytest`: pipe security, relay forwarding and dropping while closed, companion bridge, host registration.
- `cd extension && npm test`: Chrome and Edge round trips, page-visit capture, per-tab pause, nothing captured while closed.
- `cd extension && npm run test:firefox`: Firefox round trip.

The browser tests need the relay registered and Inspector's Notebook closed.

## Setup

1. `uv sync`, then `uv run inspectors-notebook-register install`.
2. `cd extension && npm install` (copies the polyfill into `src/vendor`).
3. Load `extension/src` unpacked: `chrome://extensions` and `edge://extensions` (Developer mode, Load unpacked), and `about:debugging` in Firefox (Load Temporary Add-on, pick `manifest.json`). Restart the browser after registering the relay if it was already open.

## Each browser (Chrome, Edge, Firefox)

- [ ] With the app closed, the toolbar icon is grey and its tooltip says "Inspector: app closed". The popup says "App closed" and shows Open Inspector.
- [ ] Open Inspector starts the app; the popup changes to Connected and the icon turns amber.
- [ ] The panel's status strip shows the browser, for example "Extension listening in 2 tabs" with two Defender XDR tabs open.
- [ ] Show Inspector brings the panel forward and expands it from the rail.
- [ ] Pause capture in this tab on a console tab: the popup says "paused" and the panel's tab count drops by one.
- [ ] Closing the browser leaves the app running; the panel's tab count drops accordingly.
- [ ] Closing the app turns the icon grey within a few seconds, without restarting the browser.
- [ ] "Open Inspector when I open a console": with the app closed, opening security.microsoft.com starts it.

## All three at once

- [ ] With Chrome, Edge and Firefox open on console tabs, the panel's count is the sum of the three.

## Pipe security (needs a second Windows account)

- [ ] Signed in as a second, standard account with the app running for the first account, `python -c "from inspectors_notebook import pipe; pipe.connect(r'\\.\pipe\InspectorsNotebook.<first account SID>')"` fails with access denied (get the SID with `whoami /user` as the first account).
- [ ] Running the app as the second account at the same time works independently of the first.

## Not a console

- [ ] Visiting other sites with the app open sends nothing: the panel's count does not change and the companion log shows no events.
