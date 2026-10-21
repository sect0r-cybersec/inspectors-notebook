"use strict";

// Microsoft Sentinel in the Azure portal (portal.azure.com). Sentinel in the Defender
// portal is covered by the Defender XDR parser.
//
// GAPS, to fill from purple team lab captures (tests/manual/S3-lab-capture-guide.md):
// - incidentUrls: the Sentinel incident URL format, with the ID as (?<id>...).
// - queryRequests: the Logs query request (URL, method, where the KQL sits in the body)
//   and its response shape.
// - frames: the Logs blade may run in a frame on another origin; if so, that origin
//   needs adding to the manifest's host permissions and content script matches.
// Until then this parser records page visits only; it never guesses.
globalThis.InspectorParsers.registerParser({
  id: "sentinel",
  name: "Sentinel (Azure portal)",
  version: "0.1.0",
  origins: ["https://portal.azure.com"],
  incidentUrls: [],
  queryRequests: [],
});
