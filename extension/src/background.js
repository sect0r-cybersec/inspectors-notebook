"use strict";

// Chrome and Edge run this as a service worker; Firefox loads the same files from
// manifest background.scripts instead.
if (typeof importScripts === "function") {
  importScripts(
    "vendor/browser-polyfill.min.js",
    "time.js",
    "entities.js",
    "parsers/registry.js",
    "parsers/defender.js",
    "parsers/sentinel.js",
    "consoles.js",
    "icon.js",
  );
}

const { localTimestamp } = globalThis.InspectorTime;
const Parsers = globalThis.InspectorParsers;

const HOST = "inspectors_notebook.relay";
const RECONNECT_MS = 5000;

// app: "closed" until the relay reports the companion; "unavailable" when the relay
// itself cannot start (not installed). recording is null until the companion answers.
const state = { app: "closed", recording: null };
let port = null;
let seq = 0;
const source = crypto.randomUUID(); // with seq, keeps capture order across the hop (FR-39)

function browserName() {
  if (browser.runtime.getBrowserInfo) return "firefox";
  if (navigator.userAgentData?.brands?.some((b) => b.brand === "Microsoft Edge")) return "edge";
  return "chrome";
}

// Relay connection

function connect() {
  if (port) return;
  port = browser.runtime.connectNative(HOST);
  port.onMessage.addListener(onRelayMessage);
  port.onDisconnect.addListener(() => {
    const error = browser.runtime.lastError ?? port?.error;
    port = null;
    setState({ app: error ? "unavailable" : "closed", recording: null });
    setTimeout(connect, RECONNECT_MS);
  });
  port.postMessage({ type: "hello", browser: browserName(), version: browser.runtime.getManifest().version });
}

function send(message) {
  if (port) port.postMessage(message);
}

function onRelayMessage(message) {
  if (message.type !== "status") return;
  if ("app" in message) {
    setState({ app: message.app, recording: message.app === "connected" ? state.recording : null });
  }
  if ("recording" in message) {
    // The companion's answer to our hello; report what we are listening to.
    setState({ recording: Boolean(message.recording) });
    reportTabs();
  }
}

function setState(changes) {
  Object.assign(state, changes);
  const look = state.app !== "connected" ? "closed" : state.recording ? "recording" : "connected";
  const title = {
    closed: state.app === "unavailable" ? "Inspector: relay not installed" : "Inspector: app closed",
    connected: "Inspector: connected",
    recording: "Inspector: recording",
  }[look];
  browser.action.setIcon({ imageData: iconImages(look) });
  browser.action.setTitle({ title });
}

// Tabs and capture

async function pausedTabs() {
  const { paused = [] } = await browser.storage.session.get("paused");
  return new Set(paused);
}

async function listeningTabs() {
  const [tabs, paused] = await Promise.all([browser.tabs.query({ url: CONSOLE_PATTERNS }), pausedTabs()]);
  return tabs.filter((t) => !paused.has(t.id));
}

let reportTimer = null;
function reportTabs() {
  clearTimeout(reportTimer);
  reportTimer = setTimeout(async () => {
    if (state.app === "connected") send({ type: "tabs", count: (await listeningTabs()).length });
  }, 100);
}

async function onTabUpdated(tabId, change, tab) {
  if (!("url" in change) && change.status !== "complete") return;
  reportTabs();
  const console_ = consoleFor(tab.url);
  if (!console_ || change.status !== "complete") return;

  if (state.app !== "connected") {
    // Nothing is captured or buffered while the app is closed (FR-35).
    const { openOnConsole = false } = await browser.storage.local.get("openOnConsole");
    if (openOnConsole) send({ type: "open_app" });
    return;
  }
  if ((await pausedTabs()).has(tabId)) return;
  send({
    type: "event",
    kind: "page_visit",
    source,
    seq: ++seq,
    ts: localTimestamp(),
    console: console_.id,
    tabId,
    url: tab.url,
    title: tab.title,
    incidentId: Parsers.incidentFromUrl(tab.url)?.incidentId ?? null,
  });
  if (tab.active) screenshot(tab, "navigation");
}

// Queries and results from the page hook (FR-11, FR-12). Fields are copied one by one:
// nothing else the page sends is passed on.
const TIMESTAMP = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d$/;

async function onCapture(payload, tab) {
  const console_ = tab && consoleFor(tab.url);
  if (!console_ || state.app !== "connected" || (await pausedTabs()).has(tab.id)) return;
  const common = {
    type: "event",
    kind: payload.kind,
    source,
    seq: ++seq,
    ts: TIMESTAMP.test(payload.ts) ? payload.ts : localTimestamp(),
    console: console_.id,
    tabId: tab.id,
    url: tab.url,
    queryId: String(payload.queryId),
  };
  if (payload.kind === "query") {
    send({ ...common, language: String(payload.language), query: String(payload.query) });
  } else if (payload.kind === "result") {
    const { status, rowCount, columns, rows, truncated, entities } = payload;
    send({ ...common, status, rowCount, columns, rows, truncated, entities });
    screenshot(tab, "results");
  }
}

// Screenshots (FR-13) while a case is recording: on navigation, tab switch and loaded
// results. Browsers only let an extension capture tabs if it may read every website,
// so the companion captures the browser window instead; it also skips unchanged pages.
let lastRequestAt = 0;
const REQUEST_GAP_MS = 500;

async function screenshot(tab, trigger) {
  try {
    const console_ = consoleFor(tab?.url);
    if (state.app !== "connected" || !state.recording || !tab.active || !console_) return;
    if ((await pausedTabs()).has(tab.id)) return;
    const wait = lastRequestAt + REQUEST_GAP_MS - Date.now();
    lastRequestAt = Math.max(Date.now(), lastRequestAt + REQUEST_GAP_MS);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    send({
      type: "screenshot_request",
      source,
      seq: ++seq,
      ts: localTimestamp(),
      console: console_.id,
      tabId: tab.id,
      url: tab.url,
      title: tab.title,
      trigger,
    });
  } catch {
    // tab already gone
  }
}

async function onTabActivated({ tabId }) {
  try {
    screenshot(await browser.tabs.get(tabId), "tab_switch");
  } catch {
    // tab already gone
  }
}

async function setPaused(tabId, paused) {
  const set = await pausedTabs();
  if (paused) set.add(tabId);
  else set.delete(tabId);
  await browser.storage.session.set({ paused: [...set] });
  reportTabs();
}

browser.tabs.onUpdated.addListener(onTabUpdated);
browser.tabs.onCreated.addListener(reportTabs);
browser.tabs.onActivated.addListener(onTabActivated);
browser.tabs.onRemoved.addListener((tabId) => setPaused(tabId, false));

// Popup

browser.runtime.onMessage.addListener(async (message, sender) => {
  switch (message.type) {
    case "capture":
      await onCapture(message.payload ?? {}, sender.tab);
      return true;
    case "popup_state": {
      const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
      const console_ = tab ? consoleFor(tab.url) : null;
      const { openOnConsole = false } = await browser.storage.local.get("openOnConsole");
      return {
        app: state.app,
        recording: state.recording,
        listening: (await listeningTabs()).length,
        tab: console_ && { id: tab.id, console: console_.name, paused: (await pausedTabs()).has(tab.id) },
        openOnConsole,
      };
    }
    case "open_app":
      connect();
      send({ type: "open_app" });
      return true;
    case "set_paused":
      await setPaused(message.tabId, message.paused);
      return true;
    case "set_open_on_console":
      await browser.storage.local.set({ openOnConsole: Boolean(message.value) });
      return true;
  }
});

setState({});
connect();
