// S2 tests in Chrome and Edge: messages round-trip through the real relay, and
// nothing is captured while the app is closed. Needs the relay registered
// (uv run inspectors-notebook-register install) and the companion closed.
import { chromium, expect, test } from "@playwright/test";
import { mkdtempSync, rmSync } from "node:fs";
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
  // Console pages are served locally: the tests never touch the real consoles.
  await context.route(`${CONSOLE}/**`, (route) =>
    route.fulfill({ contentType: "text/html", body: `<title>Lab ${new URL(route.request().url()).pathname}</title>` }),
  );
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

test("console page visits are captured in order with UTC timestamps", async () => {
  const page = await context.newPage();
  await page.goto(`${CONSOLE}/incidents`);
  await page.goto(`${CONSOLE}/alerts`);

  const first = await fake.waitFor((m) => m.type === "event" && m.url === `${CONSOLE}/incidents`);
  const second = await fake.waitFor((m) => m.type === "event" && m.url === `${CONSOLE}/alerts`);
  expect(first).toMatchObject({ kind: "page_visit", console: "defender", title: "Lab /incidents" });
  expect(second.seq).toBeGreaterThan(first.seq);
  expect(second.source).toBe(first.source);
  expect(first.ts).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
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
