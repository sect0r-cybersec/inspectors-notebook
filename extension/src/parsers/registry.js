"use strict";

// Console parsers (FR-16): one isolated, versioned module per console, registered here.
// A parser declares the console's origins, how to find an incident ID in a page URL
// (FR-2), and which outgoing requests carry a submitted query and how to read the query
// and its results from them (FR-12). Loaded in the page (for the request hook) and in
// the background script.
(() => {
  const MAX_ROWS = 5000; // full results stay in the case (S4); this caps one message

  const parsers = [];

  function registerParser(parser) {
    const { id, name, version, origins, incidentUrls, queryRequests } = parser;
    if (!id || !name || !version || !Array.isArray(origins) || !origins.length) {
      throw new Error("A parser needs an id, name, version and at least one origin");
    }
    if (!Array.isArray(incidentUrls) || !incidentUrls.every((r) => r instanceof RegExp)) {
      throw new Error(`${id}: incidentUrls must be a list of patterns with an (?<id>...) group`);
    }
    for (const rule of queryRequests ?? []) {
      if (!(rule.url instanceof RegExp) || typeof rule.query !== "function" || !rule.language) {
        throw new Error(`${id}: each query request needs a url pattern, a language and a query reader`);
      }
    }
    parsers.push(Object.freeze({ ...parser, queryRequests: queryRequests ?? [] }));
  }

  function parserFor(url) {
    let origin;
    try {
      origin = new URL(url).origin;
    } catch {
      return null;
    }
    return parsers.find((p) => p.origins.includes(origin)) ?? null;
  }

  function incidentFromUrl(url) {
    const parser = parserFor(url);
    for (const pattern of parser?.incidentUrls ?? []) {
      const id = pattern.exec(url)?.groups?.id;
      if (id) return { console: parser.id, incidentId: id };
    }
    return null;
  }

  // pageUrl is the console page making the request; requestUrl is where it goes.
  function matchQueryRequest(pageUrl, requestUrl, method) {
    const parser = parserFor(pageUrl);
    if (!parser) return null;
    const verb = (method || "GET").toUpperCase();
    const rule = parser.queryRequests.find((r) => r.url.test(requestUrl) && (r.method ?? "POST") === verb);
    return rule ? { parser, rule } : null;
  }

  function parseJson(body) {
    if (typeof body !== "string") return body ?? null;
    try {
      return JSON.parse(body);
    } catch {
      return null;
    }
  }

  // A reader that throws or returns nothing means "not a query": never guess.
  function readQuery(rule, body) {
    try {
      const query = rule.query(parseJson(body));
      return typeof query === "string" && query.trim() ? query : null;
    } catch {
      return null;
    }
  }

  function readResults(rule, responseBody) {
    if (typeof rule.results !== "function") return null;
    try {
      const results = rule.results(parseJson(responseBody));
      if (!results || !Array.isArray(results.columns) || !Array.isArray(results.rows)) return null;
      return results;
    } catch {
      return null;
    }
  }

  // Rows are sent capped; entities are drawn from every row.
  function summariseResults({ columns, rows }) {
    const entities = [];
    const seen = new Set();
    for (const row of rows) {
      const text = (Array.isArray(row) ? row : Object.values(row ?? {})).map((v) => String(v ?? "")).join(" ");
      for (const e of globalThis.InspectorEntities.extractEntities(text)) {
        const key = `${e.type}:${e.value}`;
        if (!seen.has(key)) {
          seen.add(key);
          entities.push(e);
        }
      }
    }
    return {
      rowCount: rows.length,
      columns: columns.map(String),
      rows: rows.slice(0, MAX_ROWS),
      truncated: rows.length > MAX_ROWS,
      entities,
    };
  }

  globalThis.InspectorParsers = {
    MAX_ROWS,
    registerParser,
    parserFor,
    incidentFromUrl,
    matchQueryRequest,
    readQuery,
    readResults,
    summariseResults,
    all: () => [...parsers],
  };
})();
