import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { LAB_ORIGIN, Parsers, extractEntities, installHook, localTimestamp } from "./load.js";

const manifest = JSON.parse(readFileSync(new URL("../../src/manifest.json", import.meta.url), "utf8"));

// Timestamps

test("timestamps are local time with the UTC offset", () => {
  const instant = new Date("2026-10-21T09:05:00.123Z");
  for (const [tz, expected] of [
    ["UTC", "2026-10-21T09:05:00.123+00:00"],
    ["Europe/London", "2026-10-21T10:05:00.123+01:00"],
    ["America/St_Johns", "2026-10-21T06:35:00.123-02:30"],
  ]) {
    process.env.TZ = tz;
    assert.equal(localTimestamp(instant), expected, tz);
    assert.equal(new Date(localTimestamp(instant)).getTime(), instant.getTime(), `${tz} keeps the instant`);
  }
  delete process.env.TZ;
});

// Entities

test("entities of each type are found once, in order", () => {
  const text =
    "j.smith ran powershell.exe -enc AAA from 10.0.0.12 to 203.0.113.7, fetching " +
    "https://evil.example.com/p.ps1 and contacting cdn.badhost.ru; mail j.smith@contoso.com; " +
    "SHA256 E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855 " +
    "md5 d41d8cd98f00b204e9800998ecf8427e, 203.0.113.7 again";
  assert.deepEqual(extractEntities(text), [
    { type: "url", value: "https://evil.example.com/p.ps1" },
    { type: "email", value: "j.smith@contoso.com" },
    { type: "ipv4", value: "10.0.0.12" },
    { type: "ipv4", value: "203.0.113.7" },
    { type: "sha256", value: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" },
    { type: "md5", value: "d41d8cd98f00b204e9800998ecf8427e" },
    { type: "file", value: "powershell.exe" },
    { type: "domain", value: "cdn.badhost.ru" },
  ]);
});

test("dotted words, column names and invalid IPs are not entities", () => {
  assert.deepEqual(extractEntities("j.smith DeviceProcessEvents.FileName 999.1.1.1 v1.2.3"), []);
  assert.deepEqual(extractEntities(""), []);
  assert.deepEqual(extractEntities(null), []);
});

// Registry

test("parsers must declare what they need", () => {
  assert.throws(() => Parsers.registerParser({ id: "x" }), /needs an id/);
  assert.throws(
    () => Parsers.registerParser({ id: "x", name: "X", version: "1", origins: ["https://x.test"], incidentUrls: ["/i/"] }),
    /incidentUrls/,
  );
  assert.throws(
    () =>
      Parsers.registerParser({
        id: "x", name: "X", version: "1", origins: ["https://x.test"], incidentUrls: [],
        queryRequests: [{ url: /q/, query: () => "" }],
      }),
    /language/,
  );
});

test("every shipped parser has a version and listens only on permitted console origins", () => {
  const shipped = Parsers.all().filter((p) => p.id !== "lab");
  assert.deepEqual(shipped.map((p) => p.id), ["defender", "sentinel"]);
  const contentMatches = manifest.content_scripts.flatMap((c) => c.matches);
  for (const p of shipped) {
    assert.match(p.version, /^\d+\.\d+\.\d+$/);
    for (const origin of p.origins) {
      assert.ok(manifest.host_permissions.includes(`${origin}/*`), `${origin} in host_permissions`);
      assert.ok(contentMatches.includes(`${origin}/*`), `${origin} in content_scripts`);
    }
  }
});

test("incident IDs come from the console's own patterns, then the generic recogniser", () => {
  assert.deepEqual(Parsers.incidentFromUrl(`${LAB_ORIGIN}/incidents/4821?tid=lab`), { console: "lab", incidentId: "4821", kind: "incident" });
  assert.equal(Parsers.incidentFromUrl(`${LAB_ORIGIN}/hunting`), null);
  assert.deepEqual(Parsers.incidentFromUrl("https://security.microsoft.com/incidents/4821/overview"), {
    console: "defender", kind: "incident", incidentId: "4821",
  });
  assert.deepEqual(Parsers.incidentFromUrl("https://elsewhere.test/cases/77"), { console: null, kind: "case", incidentId: "77" });
  assert.equal(Parsers.incidentFromUrl("not a url"), null);
});

test("query requests match on page origin, request URL and method", () => {
  const page = `${LAB_ORIGIN}/hunting`;
  assert.equal(Parsers.matchQueryRequest(page, `${LAB_ORIGIN}/api/hunt`, "post")?.parser.id, "lab");
  assert.equal(Parsers.matchQueryRequest(page, `${LAB_ORIGIN}/api/hunt`, "GET"), null);
  assert.equal(Parsers.matchQueryRequest(page, `${LAB_ORIGIN}/api/other`, "POST"), null);
  assert.equal(Parsers.matchQueryRequest("https://elsewhere.test/", `${LAB_ORIGIN}/api/hunt`, "POST"), null);
});

test("readers never guess", () => {
  const { rule } = Parsers.matchQueryRequest(`${LAB_ORIGIN}/`, `${LAB_ORIGIN}/api/hunt`, "POST");
  assert.equal(Parsers.readQuery(rule, '{"query":"DeviceInfo | take 1"}'), "DeviceInfo | take 1");
  assert.equal(Parsers.readQuery(rule, '{"query":"   "}'), null);
  assert.equal(Parsers.readQuery(rule, "not json"), null);
  assert.equal(Parsers.readQuery(rule, null), null);
  assert.equal(Parsers.readResults(rule, '{"unexpected":true}'), null);
});

test("result summaries cap rows but draw entities from all of them", () => {
  const rows = Array.from({ length: Parsers.MAX_ROWS + 3 }, (_, i) => [`HOST-${i}`, i === Parsers.MAX_ROWS + 2 ? "198.51.100.9" : ""]);
  const summary = Parsers.summariseResults({ columns: ["DeviceName", "RemoteIP"], rows });
  assert.equal(summary.rowCount, Parsers.MAX_ROWS + 3);
  assert.equal(summary.rows.length, Parsers.MAX_ROWS);
  assert.equal(summary.truncated, true);
  assert.deepEqual(summary.entities, [{ type: "ipv4", value: "198.51.100.9" }]);
  assert.deepEqual(Parsers.summariseResults({ columns: ["a"], rows: [] }), {
    rowCount: 0, columns: ["a"], rows: [], truncated: false, entities: [],
  });
});

// Page hook

function fakeWindow(respond) {
  const calls = [];
  class FakeXHR {
    open(method, url) { this.method = method; this.url = url; }
    addEventListener(type, fn) { this.listener = fn; }
    send(body) {
      calls.push({ via: "xhr", url: this.url, body });
      this.status = 200;
      this.responseType = "";
      this.responseText = respond(this.url);
      queueMicrotask(() => this.listener?.());
    }
  }
  return {
    calls,
    win: {
      location: { href: `${LAB_ORIGIN}/hunting` },
      fetch: async (input, init) => {
        calls.push({ via: "fetch", url: String(input.url ?? input), body: init?.body });
        if (String(input.url ?? input).endsWith("/fail")) throw new TypeError("network down");
        return new Response(respond(String(input.url ?? input)), { status: 200 });
      },
      XMLHttpRequest: FakeXHR,
    },
  };
}

const HUNT_RESPONSE = JSON.stringify({ schema: [{ name: "DeviceName" }, { name: "RemoteIP" }], rows: [["HOST-12", "203.0.113.7"]] });

async function settle() {
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0));
}

test("the hook captures a submitted query and its results from fetch", async () => {
  const { win } = fakeWindow(() => HUNT_RESPONSE);
  const posted = [];
  installHook(win, Parsers, (p) => posted.push(p), () => "T");
  const response = await win.fetch("/api/hunt", { method: "POST", body: JSON.stringify({ query: "DeviceNetworkEvents | take 1" }) });
  assert.equal(await response.text(), HUNT_RESPONSE, "the page still gets its response body");
  await settle();
  assert.deepEqual(posted, [
    { kind: "query", queryId: "T#1", ts: "T", console: "lab", language: "KQL", query: "DeviceNetworkEvents | take 1" },
    {
      kind: "result", queryId: "T#1", ts: "T", console: "lab", status: 200,
      rowCount: 1, columns: ["DeviceName", "RemoteIP"], rows: [["HOST-12", "203.0.113.7"]], truncated: false,
      entities: [{ type: "ipv4", value: "203.0.113.7" }],
    },
  ]);
});

test("the hook reads Request bodies without consuming them", async () => {
  const { win } = fakeWindow(() => HUNT_RESPONSE);
  const posted = [];
  installHook(win, Parsers, (p) => posted.push(p), () => "T");
  const request = new Request(`${LAB_ORIGIN}/api/hunt`, { method: "POST", body: '{"query":"AlertInfo"}' });
  await win.fetch(request);
  assert.equal(await request.text(), '{"query":"AlertInfo"}');
  await settle();
  assert.equal(posted[0].query, "AlertInfo");
});

test("the hook captures queries sent with XMLHttpRequest", async () => {
  const { win } = fakeWindow(() => HUNT_RESPONSE);
  const posted = [];
  installHook(win, Parsers, (p) => posted.push(p), () => "T");
  const xhr = new win.XMLHttpRequest();
  xhr.open("POST", "/api/hunt");
  xhr.send('{"query":"IdentityLogonEvents"}');
  await settle();
  assert.deepEqual(posted.map((p) => p.kind), ["query", "result"]);
  assert.equal(posted[0].query, "IdentityLogonEvents");
  assert.equal(posted[1].rowCount, 1);
});

test("the hook ignores other requests and never breaks the page", async () => {
  const { win, calls } = fakeWindow(() => "{}");
  const posted = [];
  installHook(win, Parsers, (p) => posted.push(p), () => "T");
  await win.fetch("/api/other", { method: "POST", body: '{"query":"secret"}' });
  await win.fetch("/api/hunt", { method: "POST", body: new Uint8Array([1, 2]) });
  await assert.rejects(win.fetch("/fail"), /network down/, "page errors still reach the page");
  win.location.href = "https://elsewhere.test/";
  await win.fetch(`${LAB_ORIGIN}/api/hunt`, { method: "POST", body: '{"query":"x"}' });
  await settle();
  assert.deepEqual(posted, []);
  assert.equal(calls.length, 4);
});

test("Defender: tenant from ?tid= and list pages are navigation only (from lab URLs)", () => {
  const tid = "00000000-0000-0000-0000-000000000001";
  assert.equal(Parsers.tenantFromUrl(`https://security.microsoft.com/alerts?tid=${tid}`), tid);
  assert.equal(Parsers.tenantFromUrl("https://security.microsoft.com/v2/advanced-hunting"), null);
  assert.equal(Parsers.tenantFromUrl("https://portal.azure.com/#view/x?tid=abc"), null);
  assert.equal(Parsers.isNavigationOnly(`https://security.microsoft.com/alerts?tid=${tid}`), true);
  assert.equal(Parsers.isNavigationOnly("https://security.microsoft.com/incidents/"), true);
  assert.equal(Parsers.isNavigationOnly("https://security.microsoft.com/incidents/4821"), false);
  assert.equal(Parsers.isNavigationOnly("https://security.microsoft.com/v2/advanced-hunting"), false);
  assert.equal(Parsers.isNavigationOnly("not a url"), false);
});
