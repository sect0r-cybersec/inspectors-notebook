"use strict";

// Defender XDR (security.microsoft.com), including Sentinel in the unified portal.
// Rules come from purple team lab captures (tests/fixtures/defender/).
//
// GAP: incidentUrls. The lab captures had no incident or alert page, so incident IDs
// are not read yet (tests/manual/S3-lab-capture-guide.md, section 3).
globalThis.InspectorParsers.registerParser({
  id: "defender",
  name: "Defender XDR",
  version: "0.3.0",
  origins: ["https://security.microsoft.com"],
  incidentUrls: [],
  // Lab URLs carry the tenant ID as ?tid=, and /alerts and /incidents are list pages.
  tenantParam: "tid",
  navigationOnly: [/^\/(alerts|incidents)\/?$/],
  queryRequests: [
    {
      // Advanced hunting: the KQL is in QueryText; columns are in Schema and each row
      // is an object keyed by column name. A failed query is a 400 with ErrorMessage.
      url: /^https:\/\/security\.microsoft\.com\/apiproxy\/hunting\/huntingQueryExecutorService\/queryExecutor\/v1\/external(\?|$)/,
      method: "POST",
      language: "KQL",
      query: (body) => body.QueryText,
      results: (json) =>
        Array.isArray(json.Schema) && Array.isArray(json.Results)
          ? {
              columns: json.Schema.map((c) => c.Name),
              rows: json.Results.map((row) => json.Schema.map((c) => row[c.Name])),
            }
          : null,
      error: (json) => json.ErrorMessage,
    },
  ],
});
