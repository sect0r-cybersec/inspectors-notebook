"use strict";

// Microsoft Sentinel in the Azure portal (portal.azure.com). Sentinel in the Defender
// portal is covered by the Defender XDR parser. Rules come from purple team lab
// captures (tests/fixtures/sentinel/).
//
// The Logs blade runs in a frame on a *.reactblade.portal.azure.net sandbox, which
// sends the query, so the request hook runs in those frames too.
//
// GAP: incidentUrls. The lab captures had no incident page, so incident IDs are not
// read yet (tests/manual/S3-lab-capture-guide.md, section 3).
globalThis.InspectorParsers.registerParser({
  id: "sentinel",
  name: "Sentinel (Azure portal)",
  version: "0.2.0",
  origins: ["https://portal.azure.com", "https://*.reactblade.portal.azure.net"],
  incidentUrls: [],
  queryRequests: [
    {
      // Log Analytics query: the KQL is in query; results are tables of columns and
      // row arrays. A failed query is a 400 whose useful message is the innermost one.
      url: /^https:\/\/api\.loganalytics\.io\/v1\/.+\/query(\?|$)/,
      method: "POST",
      language: "KQL",
      query: (body) => body.query,
      results: (json) => {
        const table = json.tables?.find((t) => t.name === "PrimaryResult") ?? json.tables?.[0];
        return table ? { columns: table.columns.map((c) => c.name), rows: table.rows } : null;
      },
      error: (json) => {
        let message = null;
        for (let e = json.error; e; e = e.innererror) message = e.message ?? message;
        return message;
      },
    },
  ],
});
