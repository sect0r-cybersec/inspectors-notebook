// Replays sanitised purple team lab captures (tests/fixtures/) through the request hook.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { Parsers, installHook } from "./load.js";

function fixture(console_, name) {
  return JSON.parse(readFileSync(new URL(`../fixtures/${console_}/${name}.json`, import.meta.url), "utf8"));
}

async function replay(f, via = "fetch") {
  const posted = [];
  const win = {
    location: { href: f.pageUrl },
    fetch: async () => new Response(f.response.body, { status: f.response.status }),
    XMLHttpRequest: class {
      open() {}
      addEventListener(type, fn) { this.done = fn; }
      send() {
        this.status = f.response.status;
        this.responseType = "";
        this.responseText = f.response.body;
        queueMicrotask(() => this.done?.());
      }
    },
  };
  installHook(win, Parsers, (p) => posted.push(p), () => "T");
  if (via === "fetch") {
    await (await win.fetch(f.request.url, { method: f.request.method, body: f.request.body })).text();
  } else {
    const xhr = new win.XMLHttpRequest();
    xhr.open(f.request.method, f.request.url);
    xhr.send(f.request.body);
  }
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
  return posted;
}

const SUBMITTED = {
  defender: (body) => JSON.parse(body).QueryText,
  sentinel: (body) => JSON.parse(body).query,
};

for (const console_ of ["defender", "sentinel"]) {
  for (const via of ["fetch", "xhr"]) {
    test(`${console_}: a query with rows is captured with its results (${via})`, async () => {
      const f = fixture(console_, "rows");
      const [query, result] = await replay(f, via);
      assert.deepEqual(query, {
        kind: "query", queryId: "T#1", ts: "T", console: console_, language: "KQL", query: SUBMITTED[console_](f.request.body),
      });
      assert.equal(result.kind, "result");
      assert.equal(result.status, 200);
      assert.equal(result.rowCount, 4);
      assert.equal(result.columns.length, 70);
      assert.ok(result.columns.includes("DeviceName"));
      for (const row of result.rows) assert.equal(row.length, result.columns.length);
      const deviceName = result.rows[0][result.columns.indexOf("DeviceName")];
      assert.equal(deviceName, "dc01.contoso.local");
      assert.ok(result.entities.some((e) => e.type === "file" && e.value === "ntoskrnl.exe"));
      assert.ok(result.entities.some((e) => e.type === "sha256"));
      assert.equal(result.error, undefined);
    });
  }

  test(`${console_}: a query with no rows is a negative finding (FR-20)`, async () => {
    const f = fixture(console_, "empty");
    const [query, result] = await replay(f);
    assert.equal(query.query, SUBMITTED[console_](f.request.body));
    assert.equal(result.rowCount, 0);
    assert.deepEqual(result.rows, []);
    assert.ok(result.columns.length > 0);
  });

  test(`${console_}: a failed query is captured with the console's error message`, async () => {
    const f = fixture(console_, "error");
    const [query, result] = await replay(f);
    assert.equal(query.query, SUBMITTED[console_](f.request.body));
    assert.equal(result.status, 400);
    assert.equal(result.rowCount, null);
    assert.match(result.error, /Failed to resolve table or column expression named/);
  });
}

test("sentinel: the Logs frame on a reactblade sandbox belongs to the Sentinel parser", () => {
  assert.equal(Parsers.parserFor("https://sandbox-5.reactblade.portal.azure.net/")?.id, "sentinel");
  assert.equal(Parsers.parserFor("https://sandbox-12.reactblade.portal.azure.net/x")?.id, "sentinel");
  assert.equal(Parsers.parserFor("https://evilreactblade.portal.azure.net/"), null);
  assert.equal(Parsers.parserFor("http://sandbox-5.reactblade.portal.azure.net/"), null);
});

test("look-alike requests from the captures are not queries", () => {
  const frame = "https://sandbox-5.reactblade.portal.azure.net/";
  const base = "https://api.loganalytics.io";
  // Query history saves the same KQL again; capturing it would duplicate the query.
  assert.equal(Parsers.matchQueryRequest(frame, `${base}/v2/subscriptions/s/resourceGroups/r/providers/Microsoft.OperationalInsights/workspaces/w/queryHistory?region=x`, "POST"), null);
  assert.equal(Parsers.matchQueryRequest(frame, "https://portal.loganalytics.io/api/userHistoryQueries/Add", "PUT"), null);
  assert.equal(Parsers.matchQueryRequest("https://security.microsoft.com/v2/advanced-hunting", "https://security.microsoft.com/api/log/Put", "POST"), null);
  // The real query endpoints, for contrast.
  assert.equal(Parsers.matchQueryRequest(frame, `${base}/v1/subscriptions/s/resourceGroups/r/providers/Microsoft.OperationalInsights/workspaces/w/query?timespan=P1D`, "POST")?.parser.id, "sentinel");
  assert.equal(Parsers.matchQueryRequest(frame, `${base}/v1/subscriptions/s/resourceGroups/r/providers/Microsoft.OperationalInsights/workspaces/w/query?timespan=P1D`, "OPTIONS"), null);
});
