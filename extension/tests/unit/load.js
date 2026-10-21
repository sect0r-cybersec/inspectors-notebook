// Loads the extension's classic scripts into this Node process, in manifest order.
// They publish themselves on globalThis, as they do in the browser.
import "../../src/time.js";
import "../../src/entities.js";
import "../../src/parsers/registry.js";
import "../../src/parsers/defender.js";
import "../../src/parsers/sentinel.js";
import "../../src/page-hook.js";

export const { localTimestamp } = globalThis.InspectorTime;
export const { extractEntities } = globalThis.InspectorEntities;
export const Parsers = globalThis.InspectorParsers;
export const { installHook } = globalThis.InspectorHook;

// A made-up console used to exercise the framework; real console rules come from lab captures.
export const LAB_ORIGIN = "https://console.lab.test";
Parsers.registerParser({
  id: "lab",
  name: "Lab console",
  version: "0.0.1",
  origins: [LAB_ORIGIN],
  incidentUrls: [/\/incidents\/(?<id>\d+)/],
  queryRequests: [
    {
      url: /\/api\/hunt$/,
      method: "POST",
      language: "KQL",
      query: (body) => body.query,
      results: (json) => ({ columns: json.schema.map((c) => c.name), rows: json.rows }),
    },
  ],
});
