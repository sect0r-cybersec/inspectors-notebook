"use strict";

// Sites the extension listens on (FR-34). The consoles below ship with permission
// (NFR-8); their ids match the console parsers in parsers/. The analyst can add any
// other HTTPS site from the popup ("Listen on this site"), which asks the browser for
// that site alone: added sites get page visits, incident detection and screenshots,
// but not query capture, which needs a console parser.
const CONSOLES = [
  { id: "defender", name: "Defender XDR", origin: "https://security.microsoft.com" },
  { id: "sentinel", name: "Azure portal", origin: "https://portal.azure.com" },
];

let addedSites = [];

function setAddedSites(origins) {
  addedSites = (origins ?? [])
    .filter((origin) => !CONSOLES.some((c) => c.origin === origin))
    .map((origin) => {
      const host = new URL(origin).hostname;
      return { id: host, name: host, origin, added: true };
    });
}

function listenedSites() {
  return [...CONSOLES, ...addedSites];
}

function consolePatterns() {
  return listenedSites().map((c) => `${c.origin}/*`);
}

function consoleFor(url) {
  let origin;
  try {
    origin = new URL(url).origin;
  } catch {
    return null;
  }
  return listenedSites().find((c) => c.origin === origin) ?? null;
}
