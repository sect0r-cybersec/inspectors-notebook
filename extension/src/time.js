"use strict";

// Capture timestamps are local time with the UTC offset, for example
// 2026-10-21T10:05:00.123+01:00: they read as local time and still pin the exact
// instant, so UTC can be shown alongside when the analyst asks for it.
(() => {
  function localTimestamp(date = new Date()) {
    const pad = (n, width = 2) => String(n).padStart(width, "0");
    const offset = -date.getTimezoneOffset();
    const sign = offset >= 0 ? "+" : "-";
    const abs = Math.abs(offset);
    return (
      `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
      `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}` +
      `${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`
    );
  }

  globalThis.InspectorTime = { localTimestamp };
})();
