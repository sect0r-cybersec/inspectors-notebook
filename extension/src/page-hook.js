"use strict";

// Runs in the console page itself (the MAIN world), so it sees a query as it is
// submitted, in the outgoing request, rather than the editor's rendered lines (FR-12).
// Only requests a parser declares are read; everything else passes straight through,
// and nothing here may break the console: every step fails silently.
(() => {
  function installHook(win, parsers, post, now) {
    let counter = 0;
    const xhrInfo = new WeakMap();

    function absolute(url) {
      return new URL(url, win.location.href).href;
    }

    function capture(requestUrl, method, body, ts) {
      const match = parsers.matchQueryRequest(win.location.href, requestUrl, method);
      if (!match) return null;
      const query = parsers.readQuery(match.rule, body);
      if (!query) return null;
      const queryId = `${ts}#${++counter}`;
      post({ kind: "query", queryId, ts, console: match.parser.id, language: match.rule.language, query });
      return { queryId, match };
    }

    function captured(found, status, responseBody) {
      const common = { kind: "result", queryId: found.queryId, ts: now(), console: found.match.parser.id, status };
      const results = parsers.readResults(found.match.rule, responseBody);
      if (results) {
        post({ ...common, ...parsers.summariseResults(results) });
        return;
      }
      const error = parsers.readError(found.match.rule, responseBody);
      if (error) post({ ...common, rowCount: null, error });
    }

    const originalFetch = win.fetch;
    if (typeof originalFetch === "function") {
      win.fetch = function (input, init) {
        let found = null;
        try {
          const isRequest = typeof input === "object" && input !== null && "url" in input;
          const url = absolute(isRequest ? input.url : String(input));
          const method = init?.method ?? (isRequest ? input.method : "GET");
          if (parsers.matchQueryRequest(win.location.href, url, method)) {
            const ts = now();
            // A Request's body can be read once, so clone it before the real fetch uses it.
            const body =
              init?.body !== undefined
                ? Promise.resolve(typeof init.body === "string" ? init.body : null)
                : isRequest
                  ? input.clone().text().catch(() => null)
                  : Promise.resolve(null);
            found = body.then((text) => capture(url, method, text, ts)).catch(() => null);
          }
        } catch {
          // never break the page
        }
        const response = originalFetch.apply(this, arguments);
        if (!found) return response;
        return response.then((res) => {
          try {
            // Clone as the response arrives, before the page reads (and uses up) the body.
            const copy = res.clone();
            found.then((f) => f && copy.text().then((t) => captured(f, res.status, t))).catch(() => {});
          } catch {
            // never break the page
          }
          return res;
        });
      };
    }

    const xhr = win.XMLHttpRequest?.prototype;
    if (xhr) {
      const open = xhr.open;
      const send = xhr.send;
      xhr.open = function (method, url) {
        try {
          xhrInfo.set(this, { method, url: absolute(url) });
        } catch {
          // never break the page
        }
        return open.apply(this, arguments);
      };
      xhr.send = function (body) {
        try {
          const info = xhrInfo.get(this);
          const found = info && capture(info.url, info.method, typeof body === "string" ? body : null, now());
          if (found) {
            this.addEventListener("loadend", () => {
              try {
                const type = this.responseType;
                if (type === "" || type === "text") captured(found, this.status, this.responseText);
                else if (type === "json") captured(found, this.status, this.response);
              } catch {
                // never break the page
              }
            });
          }
        } catch {
          // never break the page
        }
        return send.apply(this, arguments);
      };
    }
  }

  globalThis.InspectorHook = { installHook };

  if (typeof window !== "undefined" && globalThis.InspectorParsers && globalThis.InspectorTime) {
    installHook(
      window,
      globalThis.InspectorParsers,
      (payload) => window.postMessage({ __inspector: "capture", payload }, window.location.origin),
      globalThis.InspectorTime.localTimestamp,
    );
  }
})();
