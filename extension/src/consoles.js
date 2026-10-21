"use strict";

// Console sites the extension listens on (FR-34). Must match host_permissions in the
// manifest (NFR-8). Per-console parsers arrive in S3.
const CONSOLES = [
  { id: "defender", name: "Defender XDR", origin: "https://security.microsoft.com" },
  { id: "azure", name: "Azure portal", origin: "https://portal.azure.com" },
];

const CONSOLE_PATTERNS = CONSOLES.map((c) => `${c.origin}/*`);

function consoleFor(url) {
  let origin;
  try {
    origin = new URL(url).origin;
  } catch {
    return null;
  }
  return CONSOLES.find((c) => c.origin === origin) ?? null;
}
