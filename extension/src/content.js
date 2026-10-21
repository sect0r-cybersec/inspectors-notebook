"use strict";

// The extension's half of the page hook: passes captures from the console page to the
// background script. Only the two capture kinds are accepted, from this page's window.
const CAPTURE_KINDS = new Set(["query", "result"]);

window.addEventListener("message", (event) => {
  if (event.source !== window || event.origin !== location.origin) return;
  const data = event.data;
  if (!data || data.__inspector !== "capture" || !CAPTURE_KINDS.has(data.payload?.kind)) return;
  browser.runtime.sendMessage({ type: "capture", payload: data.payload }).catch(() => {});
});
