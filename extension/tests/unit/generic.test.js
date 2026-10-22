// Generic query capture (S8) for listened sites without a console parser.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Parsers, installHook } from "./load.js";

const Generic = globalThis.InspectorGenericParser;
const ADDED_SITE = "https://siem.lab.test/app/search";

// Queries

test("a query is read from a query-like field that reads like a query", () => {
  assert.equal(Generic.query({ query: "FROM logs | WHERE user == \"jdoe\"" }), 'FROM logs | WHERE user == "jdoe"');
  assert.equal(Generic.query({ params: { body: { queryString: "#event_simpleName=ProcessRollup2 | head(10)" } } }),
    "#event_simpleName=ProcessRollup2 | head(10)");
  assert.equal(Generic.query({ q: "user.name:jdoe AND host.name:HOST-12" }), "user.name:jdoe AND host.name:HOST-12");
  assert.equal(Generic.query({ sql: "SELECT * FROM events WHERE src_ip = '10.0.4.17'" }), "SELECT * FROM events WHERE src_ip = '10.0.4.17'");
});

test("form-encoded searches are read too", () => {
  assert.equal(Generic.query(null, "search=search%20index%3Dmain%20user%3Djdoe&output_mode=json"), "search index=main user=jdoe");
});

test("plain words, other fields and GraphQL are not queries", () => {
  assert.equal(Generic.query({ q: "jdoe" }), null); // a name lookup, not a query
  assert.equal(Generic.query({ comment: "host | where x == 1" }), null); // not a query field
  assert.equal(Generic.query({ query: "query Tickets { tickets(first: 5) { id } }", operationName: "Tickets", variables: {} }), null);
  assert.equal(Generic.query({ query: "{ viewer { login } }" }), null);
  assert.equal(Generic.query(["query", "x | y"]), null);
  assert.equal(Generic.query(null, "not a form"), null);
});

test("with several query fields, the longest query wins", () => {
  assert.equal(Generic.query({ q: "a:b", body: { query: "process where name == \"a.exe\" | head 5" } }), 'process where name == "a.exe" | head 5');
});

// Results

test("results are read from common table shapes", () => {
  const expected = { columns: ["host", "count"], rows: [["HOST-12", 41], ["HOST-07", 2]] };
  // Named columns with value rows, plain or as objects with a name.
  assert.deepEqual(Generic.results({ columns: [{ name: "host", type: "keyword" }, { name: "count" }], values: [["HOST-12", 41], ["HOST-07", 2]] }), expected);
  assert.deepEqual(Generic.results({ columns: ["host", "count"], rows: [["HOST-12", 41], ["HOST-07", 2]] }), expected);
  // A list of records, wrapped or not.
  assert.deepEqual(Generic.results({ response: { events: [{ host: "HOST-12", count: 41 }, { host: "HOST-07", count: 2 }] } }), expected);
  // Search hits.
  assert.deepEqual(Generic.results({ hits: { total: { value: 2 }, hits: [{ _source: { host: "HOST-12", count: 41 } }, { _source: { host: "HOST-07", count: 2 } }] } }), expected);
});

test("records with different fields share one column list, and nested values become text", () => {
  assert.deepEqual(Generic.results({ results: [{ a: 1 }, { b: { c: 2 } }] }), { columns: ["a", "b"], rows: [[1, undefined], [undefined, '{"c":2}']] });
});

test("an empty result list is zero rows; anything else unread is left alone", () => {
  assert.deepEqual(Generic.results({ results: [] }), { columns: [], rows: [] });
  assert.equal(Generic.results({ id: "abc", is_running: true }), null);
  assert.equal(Generic.results({ data: ["a", "b"] }), null);
  assert.equal(Generic.results("plain text"), null);
});

test("errors are read from common error shapes", () => {
  assert.equal(Generic.error({ error: "Unknown column [usr]" }), "Unknown column [usr]");
  assert.equal(Generic.error({ error: { root_cause: [{ reason: "parsing_exception" }] } }), "parsing_exception");
  assert.equal(Generic.error({ error: { message: "Query timed out" } }), "Query timed out");
  assert.equal(Generic.error({ errors: [{ message: "Syntax error at 1:5" }] }), "Syntax error at 1:5");
  assert.equal(Generic.error({ ok: true }), null);
});

// Through the hook

test("a site with no console parser falls back to generic capture, for POST and PUT only", () => {
  assert.equal(Parsers.matchQueryRequest(ADDED_SITE, "https://siem.lab.test/api/query", "POST")?.parser.id, "generic");
  assert.equal(Parsers.matchQueryRequest(ADDED_SITE, "https://siem.lab.test/api/query", "put")?.parser.id, "generic");
  assert.equal(Parsers.matchQueryRequest(ADDED_SITE, "https://siem.lab.test/api/query", "GET"), null);
  // A console parser's own rules win on its site: no generic capture there.
  assert.equal(Parsers.matchQueryRequest("https://security.microsoft.com/v2/advanced-hunting", "https://security.microsoft.com/api/log/Put", "POST"), null);
});

function fixture(console_, name) {
  return JSON.parse(readFileSync(new URL(`../fixtures/${console_}/${name}.json`, import.meta.url), "utf8"));
}

async function replay(f, pageUrl) {
  const posted = [];
  const win = {
    location: { href: pageUrl },
    fetch: async () => new Response(f.response.body, { status: f.response.status }),
  };
  installHook(win, Parsers, (p) => posted.push(p), () => "T");
  await (await win.fetch(f.request.url, { method: f.request.method, body: f.request.body })).text();
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
  return posted;
}

test("lab captures from Defender and Sentinel read the same through generic capture", async () => {
  for (const console_ of ["defender", "sentinel"]) {
    for (const name of ["rows", "empty"]) {
      const f = fixture(console_, name);
      const [specificQuery, specificResult] = await replay(f, f.pageUrl);
      const [genericQuery, genericResult] = await replay(f, ADDED_SITE);
      const where = `${console_}/${name}`;
      assert.equal(genericQuery.console, "generic", where);
      assert.equal(genericQuery.query, specificQuery.query, where);
      assert.equal(genericResult.rowCount, specificResult.rowCount, where);
      if (specificResult.rowCount) assert.deepEqual([...genericResult.columns].sort(), [...specificResult.columns].sort(), where);
      assert.deepEqual(genericResult.entities.map((e) => e.value).sort(), specificResult.entities.map((e) => e.value).sort(), where);
    }
    const f = fixture(console_, "error");
    const [, genericError] = await replay(f, ADDED_SITE);
    assert.ok(typeof genericError?.error === "string" && genericError.error.length > 0, `${console_}/error`);
  }
});
