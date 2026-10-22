"use strict";

// Generic query capture (S8): for any listened site without a console parser, such as a
// SIEM, EDR or log search the analyst has added from the popup. Nothing here is specific
// to a platform. A query is a string in a request body under a query-like field name
// that also reads like a query; results are read only from common table shapes. Anything
// it cannot read confidently is left alone (never guess): the page visit, incident
// detection and screenshots still work, and a console parser can always do better.
(() => {
  // Field names that carry a query, compared lower-case without _ or -.
  const QUERY_KEYS = new Set([
    "query", "querystring", "querytext", "q", "search", "searchquery", "esql", "kql", "sql", "spl", "statement",
  ]); // fmt: skip
  // A pipe, a query keyword, or a field compared with a value.
  const QUERY_SYNTAX =
    /\||\b(where|select|from|search|filter|stats|summarize|sort|limit|take|project|eval|lookup|join)\b|[\w.@]+\s*(==|!=|=~|>=|<=|:|=|>|<)\s*\S/i;
  // GraphQL documents are app plumbing, not the analyst's query.
  const GRAPHQL = /^\s*(\{|(query|mutation|subscription|fragment)\b)/;
  const MAX_DEPTH = 4;
  const MAX_QUERY = 20000;
  // Keys under which a list of result records is commonly found, compared lower-case.
  const RECORD_KEYS = ["results", "rows", "events", "records", "data", "items", "hits", "values"];

  const normal = (key) => String(key).toLowerCase().replace(/[_-]/g, "");

  function bodyObject(parsed, raw) {
    if (parsed && typeof parsed === "object") return parsed;
    if (typeof raw !== "string" || !raw.includes("=")) return null;
    try {
      return Object.fromEntries(new URLSearchParams(raw)); // form-encoded searches
    } catch {
      return null;
    }
  }

  function candidates(value, depth, out) {
    if (!value || typeof value !== "object" || depth > MAX_DEPTH) return out;
    for (const [key, child] of Object.entries(value)) {
      if (typeof child === "string") {
        if (QUERY_KEYS.has(normal(key))) out.push(child);
      } else {
        candidates(child, depth + 1, out);
      }
    }
    return out;
  }

  function query(parsed, raw) {
    const body = bodyObject(parsed, raw);
    if (!body || Array.isArray(body)) return null;
    if ("operationName" in body && "variables" in body) return null; // a GraphQL call
    // Judged on the trimmed text, but returned exactly as the analyst submitted it.
    const found = candidates(body, 0, []).filter((text) => {
      const t = text.trim();
      return t.length >= 3 && t.length <= MAX_QUERY && !GRAPHQL.test(t) && QUERY_SYNTAX.test(t);
    });
    if (!found.length) return null;
    return found.reduce((a, b) => (b.length > a.length ? b : a));
  }

  function cell(value) {
    return value !== null && typeof value === "object" ? JSON.stringify(value) : value;
  }

  function columnName(column) {
    if (typeof column === "string") return column;
    return column?.name ?? column?.Name ?? column?.field ?? null;
  }

  // Records (plain objects) as a table: columns in first-seen order across the rows.
  function fromRecords(records) {
    if (!records.every((r) => r !== null && typeof r === "object" && !Array.isArray(r))) return null;
    const columns = [];
    const seen = new Set();
    for (const record of records.slice(0, 50)) {
      for (const key of Object.keys(record)) {
        if (!seen.has(key)) {
          seen.add(key);
          columns.push(key);
        }
      }
    }
    return { columns, rows: records.map((r) => columns.map((c) => cell(r[c]))) };
  }

  function field(json, name) {
    const key = Object.keys(json).find((k) => k.toLowerCase() === name);
    return key === undefined ? undefined : json[key];
  }

  function table(json, depth) {
    if (!json || typeof json !== "object" || Array.isArray(json) || depth > MAX_DEPTH) return null;
    // Named columns with row arrays: {columns, rows} or {columns, values}.
    const columns = field(json, "columns");
    const rowArrays = field(json, "rows") ?? field(json, "values");
    if (Array.isArray(columns) && Array.isArray(rowArrays) && rowArrays.every(Array.isArray)) {
      const names = columns.map(columnName);
      if (names.every((n) => typeof n === "string")) return { columns: names, rows: rowArrays.map((r) => r.map(cell)) };
    }
    // A list of tables: the first one.
    const tables = field(json, "tables");
    if (Array.isArray(tables) && tables.length) return table(tables[0], depth + 1);
    // Search hits: {hits: {hits: [{_source: {...}}]}}.
    const hits = field(json, "hits");
    if (hits && Array.isArray(hits.hits)) {
      return fromRecords(hits.hits.map((h) => (h && typeof h === "object" ? (h._source ?? h.fields ?? h) : h)));
    }
    // A list of records under a common key.
    for (const name of RECORD_KEYS) {
      const records = field(json, name);
      if (Array.isArray(records)) {
        const result = records.length ? fromRecords(records) : { columns: [], rows: [] };
        if (result) return result;
      }
    }
    // Wrapped responses, such as {response: {...}} or {rawResponse: {...}}.
    for (const child of Object.values(json)) {
      const result = table(child, depth + 1);
      if (result) return result;
    }
    return null;
  }

  function results(json) {
    return table(json, 0);
  }

  function error(json) {
    if (!json || typeof json !== "object") return null;
    const e = field(json, "error") ?? field(json, "errormessage");
    if (typeof e === "string") return e;
    if (e && typeof e === "object") {
      return e.message ?? e.reason ?? e.root_cause?.[0]?.reason ?? null;
    }
    const errors = field(json, "errors");
    if (Array.isArray(errors) && errors.length) return errors[0]?.message ?? (typeof errors[0] === "string" ? errors[0] : null);
    return null;
  }

  // Applies to POST and PUT requests from the page; reading the body decides the rest.
  const rule = Object.freeze({ language: "Query", query, results, error, methods: ["POST", "PUT"] });
  const parser = Object.freeze({ id: "generic", name: "Any site", version: "0.1.0", origins: [], queryRequests: [rule] });

  globalThis.InspectorGenericParser = { parser, rule, query, results, error };
})();
