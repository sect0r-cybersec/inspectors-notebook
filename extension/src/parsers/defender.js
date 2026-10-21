"use strict";

// Defender XDR (security.microsoft.com), including Sentinel in the unified portal.
//
// GAPS, to fill from purple team lab captures (tests/manual/S3-lab-capture-guide.md):
// - incidentUrls: the incident and alert page URL formats, with the ID as (?<id>...).
// - queryRequests: the advanced hunting request (URL, method, where the KQL sits in the
//   body) and the shape of its response (columns and rows).
// Until then this parser records page visits only; it never guesses.
globalThis.InspectorParsers.registerParser({
  id: "defender",
  name: "Defender XDR",
  version: "0.1.0",
  origins: ["https://security.microsoft.com"],
  incidentUrls: [],
  queryRequests: [],
});
