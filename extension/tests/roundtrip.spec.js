// S2 tests in Chrome and Edge: messages round-trip through the real relay, and
// nothing is captured while the app is closed. Needs the relay registered
// (uv run inspectors-notebook-register install) and the companion closed.
import { chromium, expect, test } from "@playwright/test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { FakeCompanion } from "./fake-companion.js";

const EXTENSION = resolve(dirname(fileURLToPath(import.meta.url)), "..", "src");
const EXTENSION_ID = "ekjdcglidekbodkolhakfhleobcjidag";
const CONSOLE = "https://security.microsoft.com";

let fake;
let context;
let profile;

// One browser launch, shared by the tests: see playwright.config.js for why.
test.describe.configure({ mode: "serial" });

test.beforeAll(async ({}, testInfo) => {
  profile = mkdtempSync(join(tmpdir(), "inspector-ext-"));
  // Chrome 137 and later ignore --load-extension; loading over CDP works in Chrome and Edge.
  context = await chromium.launchPersistentContext(profile, {
    channel: testInfo.project.use.channel,
    headless: true,
    ignoreDefaultArgs: ["--disable-extensions"],
    args: ["--enable-unsafe-extension-debugging"],
  });
  const cdp = await context.browser().newBrowserCDPSession();
  const { id } = await cdp.send("Extensions.loadUnpacked", { path: EXTENSION });
  expect(id).toBe(EXTENSION_ID);
  // Console pages are served locally: the tests never touch the real consoles. Each
  // path gets its own colour, so different pages look different in screenshots.
  await context.route(`${CONSOLE}/**`, (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname.startsWith("/api/")) return route.fulfill({ contentType: "application/json", body: '{"ok":true}' });
    const hue = [...pathname].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 0);
    return route.fulfill({
      contentType: "text/html",
      body: `<title>Lab ${pathname}</title><body style="margin:0;height:100vh;background:hsl(${hue} 70% 45%)">`,
    });
  });
});

test.afterAll(async () => {
  await context?.close();
  rmSync(profile, { recursive: true, force: true });
});

// Each test gets a fresh companion; the relay reconnects to it and replays the hello.
test.beforeEach(async () => {
  fake = await FakeCompanion.start();
  await fake.waitFor((m) => m.type === "tabs");
});

test.afterEach(async () => {
  for (const page of context.pages().slice(1)) await page.close();
  await fake?.stop();
  await expect.poll(async () => (await extensionState()).app).toBe("closed");
});

async function background() {
  return context.serviceWorkers()[0] ?? (await context.waitForEvent("serviceworker"));
}

async function extensionState() {
  return (await background()).evaluate(() => ({ ...state }));
}

async function popup() {
  const page = await context.newPage();
  await page.goto(`chrome-extension://${EXTENSION_ID}/popup.html`);
  return page;
}

test("hello and tab count round-trip through relay and companion", async ({}, testInfo) => {
  const expected = testInfo.project.name === "msedge" ? "edge" : "chrome";
  await fake.waitFor((m) => m.type === "hello" && m.browser === expected);
  // The extension only reports tabs after the companion's reply reaches it.
  expect(fake.messages.find((m) => m.type === "tabs")).toEqual({ type: "tabs", count: 0 });
  await expect.poll(extensionState).toEqual({ app: "connected", recording: false });

  const ui = await popup();
  await expect(ui.locator(".app-text")).toHaveText("Connected");
  await expect(ui.getByRole("button", { name: "Show Inspector" })).toBeVisible();
});

test("console page visits are captured in order with local timestamps", async () => {
  const page = await context.newPage();
  await page.goto(`${CONSOLE}/incidents`);
  await page.goto(`${CONSOLE}/alerts`);

  const first = await fake.waitFor((m) => m.type === "event" && m.url === `${CONSOLE}/incidents`);
  const second = await fake.waitFor((m) => m.type === "event" && m.url === `${CONSOLE}/alerts`);
  expect(first).toMatchObject({ kind: "page_visit", console: "defender", title: "Lab /incidents", incidentId: null });
  expect(second.seq).toBeGreaterThan(first.seq);
  expect(second.source).toBe(first.source);
  // Local time with the UTC offset, so it is still an exact instant.
  expect(first.ts).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$/);
  expect(Math.abs(Date.parse(first.ts) - Date.now())).toBeLessThan(60_000);
  await fake.waitFor((m) => m.type === "tabs" && m.count === 1);

  // Non-console pages are not captured.
  await page.goto("about:blank");
  await page.goto(`${CONSOLE}/hunting`);
  await fake.waitFor((m) => m.url === `${CONSOLE}/hunting`);
  expect(fake.messages.some((m) => m.type === "event" && !m.url.startsWith(CONSOLE))).toBe(false);
});

test("a paused tab is not captured", async () => {
  const page = await context.newPage();
  await page.goto(`${CONSOLE}/incidents`);
  const { tabId } = await fake.waitFor((m) => m.type === "event");

  const ui = await popup();
  await ui.evaluate((id) => browser.runtime.sendMessage({ type: "set_paused", tabId: id, paused: true }), tabId);
  await fake.waitFor((m) => m.type === "tabs" && m.count === 0);
  await page.goto(`${CONSOLE}/paused-page`);

  await ui.evaluate((id) => browser.runtime.sendMessage({ type: "set_paused", tabId: id, paused: false }), tabId);
  await page.goto(`${CONSOLE}/resumed-page`);
  await fake.waitFor((m) => m.url === `${CONSOLE}/resumed-page`);
  expect(fake.messages.some((m) => m.url === `${CONSOLE}/paused-page`)).toBe(false);
});

test("nothing is captured while the app is closed", async () => {
  await fake.stop();
  await expect.poll(async () => (await extensionState()).app).toBe("closed");

  const ui = await popup();
  await expect(ui.locator(".app-text")).toHaveText("App closed");
  await expect(ui.getByRole("button", { name: "Open Inspector" })).toBeVisible();

  const page = await context.newPage();
  await page.goto(`${CONSOLE}/while-closed`);
  await page.waitForTimeout(1500);

  fake = await FakeCompanion.start();
  await fake.waitFor((m) => m.type === "hello");
  await fake.waitFor((m) => m.type === "tabs" && m.count === 1);
  await page.waitForTimeout(1000);
  expect(fake.messages.filter((m) => m.type === "event")).toEqual([]);
});

test("console pages keep working with the request hook installed", async () => {
  const page = await context.newPage();
  await page.goto(`${CONSOLE}/hunting`);
  const results = await page.evaluate(async () => {
    const viaFetch = await (await fetch("/api/hunt", { method: "POST", body: '{"query":"DeviceInfo"}' })).json();
    const viaXhr = await new Promise((done) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/hunt");
      xhr.onload = () => done(JSON.parse(xhr.responseText));
      xhr.send('{"query":"DeviceInfo"}');
    });
    return { viaFetch, viaXhr, hooked: typeof window.InspectorHook };
  });
  expect(results).toEqual({ viaFetch: { ok: true }, viaXhr: { ok: true }, hooked: "object" });
  // /api/hunt is not a console query endpoint, so nothing is captured.
  await page.waitForTimeout(500);
  expect(fake.messages.filter((m) => m.kind === "query" || m.kind === "result")).toEqual([]);
});

test("screenshot requests while recording: navigation and tab switch", async () => {
  await fake.stop();
  fake = await FakeCompanion.start({ recording: true });
  await fake.waitFor((m) => m.type === "tabs");
  const requestFor = (path, trigger) =>
    fake.waitFor((m) => m.type === "screenshot_request" && m.url === `${CONSOLE}${path}` && m.trigger === trigger);

  const a = await context.newPage();
  await a.goto(`${CONSOLE}/incidents`);
  const first = await requestFor("/incidents", "navigation");
  // The companion finds the browser window by the tab's title, then captures it.
  expect(first).toMatchObject({ console: "defender", title: "Lab /incidents" });
  expect(first.ts).toMatch(/[+-]\d\d:\d\d$/);

  const b = await context.newPage();
  await b.goto(`${CONSOLE}/alerts`);
  await requestFor("/alerts", "navigation");

  await a.bringToFront();
  await requestFor("/incidents", "tab_switch");
});

test("no screenshots unless a case is recording", async () => {
  const page = await context.newPage();
  await page.goto(`${CONSOLE}/not-recording`);
  await fake.waitFor((m) => m.type === "event" && m.url === `${CONSOLE}/not-recording`);
  await page.waitForTimeout(1500);
  expect(fake.messages.filter((m) => m.type === "screenshot_request")).toEqual([]);
});

// Lab fixtures replayed in the real browser: proves the hook runs where each console
// sends its queries. Responses are served locally from tests/fixtures/.
function labFixture(console_, name) {
  return JSON.parse(readFileSync(new URL(`fixtures/${console_}/${name}.json`, import.meta.url), "utf8"));
}

test("Defender advanced hunting queries are captured with their results", async () => {
  const f = labFixture("defender", "rows");
  const endpoint = f.request.url.split("?")[0];
  await context.route(`${endpoint}**`, (route) =>
    route.fulfill({ status: f.response.status, contentType: "application/json", body: f.response.body }),
  );
  try {
    const page = await context.newPage();
    await page.goto(`${CONSOLE}/v2/advanced-hunting`);
    await page.evaluate(async ({ url, body }) => (await fetch(url, { method: "POST", body })).json(), f.request);

    const query = await fake.waitFor((m) => m.kind === "query");
    expect(query).toMatchObject({ console: "defender", language: "KQL", query: JSON.parse(f.request.body).QueryText });
    const result = await fake.waitFor((m) => m.kind === "result");
    expect(result).toMatchObject({ console: "defender", queryId: query.queryId, status: 200, rowCount: 4 });
    expect(result.columns).toContain("DeviceName");
  } finally {
    await context.unroute(`${endpoint}**`);
  }
});

test("Sentinel Logs queries are captured from the reactblade frame", async () => {
  const f = labFixture("sentinel", "rows");
  const frameUrl = f.pageUrl; // https://sandbox-5.reactblade.portal.azure.net/
  const routes = {
    "https://portal.azure.com/**": (route) =>
      route.fulfill({ contentType: "text/html", body: `<title>Sentinel lab</title><iframe src="${frameUrl}"></iframe>` }),
    [`${frameUrl}**`]: (route) => route.fulfill({ contentType: "text/html", body: "<title>Logs</title>" }),
    "https://api.loganalytics.io/**": (route) =>
      route.fulfill({
        status: f.response.status,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "*" },
        body: f.response.body,
      }),
  };
  for (const [url, handler] of Object.entries(routes)) await context.route(url, handler);
  try {
    const page = await context.newPage();
    await page.goto("https://portal.azure.com/#view/Microsoft_Azure_Security_Insights");
    await expect.poll(() => page.frames().some((fr) => fr.url().startsWith(frameUrl))).toBe(true);
    const frame = page.frames().find((fr) => fr.url().startsWith(frameUrl));
    await frame.waitForLoadState();
    await frame.evaluate(async ({ url, body }) => (await fetch(url, { method: "POST", body })).json(), f.request);

    const query = await fake.waitFor((m) => m.kind === "query");
    expect(query).toMatchObject({ console: "sentinel", query: JSON.parse(f.request.body).query });
    expect(query.url).toMatch(/^https:\/\/portal\.azure\.com\//); // the tab, not the frame
    const result = await fake.waitFor((m) => m.kind === "result");
    expect(result).toMatchObject({ console: "sentinel", rowCount: 4 });
  } finally {
    for (const url of Object.keys(routes)) await context.unroute(url);
  }
});

test("incident pages are recognised without console-specific rules", async () => {
  const page = await context.newPage();
  await page.goto(`${CONSOLE}/incidents/4821/overview`);
  const visit = await fake.waitFor((m) => m.type === "event" && m.url === `${CONSOLE}/incidents/4821/overview`);
  expect(visit).toMatchObject({ incidentId: "4821", recordKind: "incident", navigationOnly: false });
  await page.goto(`${CONSOLE}/incidents`);
  const list = await fake.waitFor((m) => m.type === "event" && m.url === `${CONSOLE}/incidents`);
  expect(list).toMatchObject({ incidentId: null, navigationOnly: true });
});

test("interval screenshots of the active console tab while recording", async () => {
  await fake.stop();
  fake = await FakeCompanion.start({ recording: true, interval: 1 });
  await fake.waitFor((m) => m.type === "tabs");
  const page = await context.newPage();
  await page.goto(`${CONSOLE}/v2/advanced-hunting`);
  const shot = await fake.waitFor((m) => m.type === "screenshot_request" && m.trigger === "interval", 10_000);
  expect(shot).toMatchObject({ console: "defender", url: `${CONSOLE}/v2/advanced-hunting` });
});
