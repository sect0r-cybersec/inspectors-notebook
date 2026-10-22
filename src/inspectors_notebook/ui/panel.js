"use strict";

const root = document.documentElement;
const panel = document.querySelector(".panel");
const rail = document.querySelector(".rail");
const handle = document.querySelector(".resize");
const listener = document.querySelector(".listener");
const KEY_STEP = 16;

let state = null;

function api() {
  return window.pywebview.api;
}

// Python also calls this when a browser connects or reports its console tabs.
function render(next) {
  state = next;
  root.dataset.theme = state.theme;
  root.dataset.side = state.side;
  panel.hidden = state.collapsed;
  rail.hidden = !state.collapsed;
  handle.setAttribute("aria-valuenow", state.width);
  listener.textContent = listenerText(state.listener);

  const labels = {
    theme: state.theme === "dark" ? "Switch to light mode" : "Switch to dark mode",
    side: state.side === "right" ? "Move to the left side of the screen" : "Move to the right side of the screen",
  };
  for (const button of document.querySelectorAll("[data-label]")) {
    const label = labels[button.dataset.label];
    button.setAttribute("aria-label", label);
    button.title = label;
  }
  renderCase();
}

function listenerText({ browsers, tabs }) {
  if (browsers === 0) return "No browsers connected";
  if (tabs === 0) return "Extension connected, no console tabs open";
  return `Extension listening in ${tabs} ${tabs === 1 ? "tab" : "tabs"}`;
}

const actions = {
  theme: () => api().toggle_theme(),
  side: () => api().toggle_side(),
  collapse: () => api().toggle_collapse(),
};

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button || !state) return;
  const focusAction = button.dataset.action;
  render(await actions[focusAction]());
  // Collapse and expand swap which buttons exist, so keep focus on the matching control.
  const visible = state.collapsed ? rail : panel;
  visible.querySelector(`[data-action="${focusAction}"]`)?.focus();
});

// Drag the inner edge to resize (FR-52). Only one preview call is in flight at a time.

let drag = null;

function widthAt(screenX) {
  const dx = screenX - drag.startX;
  return Math.round(state.side === "right" ? drag.startWidth - dx : drag.startWidth + dx);
}

async function sendPreview() {
  while (drag && drag.pending !== null) {
    const width = drag.pending;
    drag.pending = null;
    await api().preview_width(width);
  }
  if (drag) drag.sending = false;
}

handle.addEventListener("pointerdown", (event) => {
  if (!state) return;
  handle.setPointerCapture(event.pointerId);
  drag = { startX: event.screenX, startWidth: state.width, pending: null, sending: false };
});

handle.addEventListener("pointermove", (event) => {
  if (!drag) return;
  drag.pending = widthAt(event.screenX);
  if (!drag.sending) {
    drag.sending = true;
    sendPreview();
  }
});

async function endDrag(event) {
  if (!drag) return;
  const width = widthAt(event.screenX);
  drag = null;
  render(await api().set_width(width));
}

handle.addEventListener("pointerup", endDrag);
handle.addEventListener("pointercancel", endDrag);

handle.addEventListener("keydown", async (event) => {
  if (!state || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
  event.preventDefault();
  // Arrow towards the screen centre widens the panel.
  const widen = (event.key === "ArrowLeft") === (state.side === "right");
  render(await api().set_width(state.width + (widen ? KEY_STEP : -KEY_STEP)));
});

window.addEventListener("pywebviewready", async () => render(await api().get_state()));

// Cases (S4): start prompt, recording strip and case header. Values that come from
// console pages are only ever set as text, never as HTML.

const $ = (selector) => document.querySelector(selector);
const CONSOLE_NAMES = { defender: "Defender XDR", sentinel: "Sentinel" };
let formOpen = false;
let timer = { seconds: 0, at: 0, running: false };

function clock(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mmss = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return h ? `${h}:${mmss}` : mmss;
}

function tick() {
  const seconds = timer.seconds + (timer.running ? (Date.now() - timer.at) / 1000 : 0);
  for (const el of document.querySelectorAll(".rec-timer")) el.textContent = clock(seconds);
}
setInterval(tick, 1000);

function chip(text, { onRemove, onPromote } = {}) {
  const el = document.createElement("span");
  el.className = onPromote ? "chip suggested" : "chip";
  el.append(text);
  const button = document.createElement("button");
  if (onRemove) {
    button.textContent = "×";
    button.setAttribute("aria-label", `Remove ${text}`);
    button.title = `Remove ${text}`;
    button.addEventListener("click", onRemove);
  } else {
    button.textContent = "+";
    button.setAttribute("aria-label", `Add ${text} as a case entity`);
    button.title = "Add as a case entity";
    button.addEventListener("click", onPromote);
  }
  el.append(button);
  return el;
}

function addEntityChip() {
  const add = document.createElement("button");
  add.className = "chip add";
  add.textContent = "+ Entity";
  add.addEventListener("click", () => {
    const box = document.createElement("span");
    box.className = "chip";
    const input = document.createElement("input");
    input.setAttribute("aria-label", "New entity");
    input.placeholder = "Host, user, IP, hash…";
    input.addEventListener("keydown", async (e) => {
      if (e.key === "Enter" && input.value.trim()) render(await api().add_entity(input.value));
      if (e.key === "Escape") renderCase();
    });
    box.append(input);
    add.replaceWith(box);
    input.focus();
  });
  return add;
}

function renderCase() {
  const { case: c, suggestion: s } = state;

  $(".status").hidden = Boolean(c);
  $(".recording").hidden = !c;
  $(".case-header").hidden = !c;
  $(".start-form").hidden = Boolean(c) || !formOpen;
  $(".empty").hidden = Boolean(c) || formOpen || Boolean(s);
  $(".rail-rec").hidden = !c;

  timer = { seconds: c ? c.elapsedSeconds : 0, at: Date.now(), running: c?.state === "recording" };
  tick();

  if (c) {
    const paused = c.state === "paused";
    $(".recording").classList.toggle("paused", paused);
    $(".rec-label").textContent = paused ? "Paused" : "Recording";
    $(".pause-label").textContent = paused ? "Resume" : "Pause";
    $(".rail-rec").setAttribute("aria-label", paused ? "Case paused" : "Recording");

    const where = [c.incidentId ? `Incident ${c.incidentId}` : "Manual case", CONSOLE_NAMES[c.console] ?? c.console, c.tenant && `Tenant ${c.tenant}`];
    $(".case-meta").textContent = where.filter(Boolean).join(" · ");
    $(".case-title").textContent = c.title || "Untitled case";

    const remove = (value) => async () => render(await api().remove_entity(value));
    const promote = (value) => async () => render(await api().add_entity(value));
    // Captures re-render the panel often; don't throw away an entity being typed.
    const typing = $(".case-entities").contains(document.activeElement) && document.activeElement.tagName === "INPUT";
    if (!typing) {
      $(".case-entities").replaceChildren(...c.entities.map((e) => chip(e, { onRemove: remove(e) })), addEntityChip());
    }
    $(".counts").textContent = `${c.counts.keep} kept · ${c.counts.review} for review · ${c.counts.hide} hidden`;
    $(".seen").hidden = !c.suggestedEntities.length;
    $(".seen-entities").replaceChildren(...c.suggestedEntities.map((e) => chip(e, { onPromote: promote(e) })));
  }

  $(".suggestion").hidden = !s;
  if (s) {
    const switching = s.kind === "switch";
    $(".suggestion-kicker").textContent = switching ? "A different incident is open" : "Incident detected";
    $(".suggestion-title").textContent = s.title || `Incident ${s.incidentId}`;
    $(".suggestion-meta").textContent = [`Incident ${s.incidentId}`, CONSOLE_NAMES[s.console] ?? s.console].filter(Boolean).join(" · ");
    $('[data-case="accept_suggestion"]').textContent = switching ? "Switch case" : s.resume ? "Resume case" : "Start case";
    $('.suggestion [data-case="pause"]').hidden = !switching;
    $('[data-case="dismiss_suggestion"]').textContent = switching ? "Keep going" : "Not now";
  }
  renderTimelineArea();
}

const caseActions = {
  open_form: () => {
    formOpen = true;
    renderCase();
    $('.start-form [name="incidentId"]').focus();
  },
  close_form: () => {
    formOpen = false;
    renderCase();
  },
  pause_or_resume: async () => render(await (state.case.state === "paused" ? api().resume_case() : api().pause_case())),
  pause: async () => render(await api().pause_case()),
  stop: async () => render(await api().stop_case()),
  accept_suggestion: async () => render(await api().accept_suggestion()),
  dismiss_suggestion: async () => render(await api().dismiss_suggestion()),
};

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-case]");
  if (button && state) caseActions[button.dataset.case]();
});

$(".start-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = Object.fromEntries(new FormData(event.target));
  formOpen = false;
  event.target.reset();
  render(await api().start_case(form));
});

// Timeline, export, cases and settings (S5). As above, values from consoles and logs
// are set as text, and nothing is re-rendered while the analyst is typing in it.

const REASONS = {
  entity: "Case entity",
  negative_finding: "Negative finding",
  duplicate: "Duplicate",
  navigation: "Navigation only",
  idle: "While you were away",
  other_tenant: "Different tenant",
  analyst: "Your choice",
};
const TAB_HELP = {
  review: "Inspector isn't sure about these. Keep or hide each one.",
  hide: "Hidden events stay in the case and can be restored.",
};
const ICONS = {
  star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"></path>',
  comment: '<path d="M4 5h16v11H9l-5 4z"></path>',
  hide: '<path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z"></path><path d="M4 4l16 16"></path>',
  restore: '<path d="M3 12s3.5-6 9-6 9 6 9 6-3.5 6-9 6-9-6-9-6z"></path><circle cx="12" cy="12" r="2.5"></circle>',
  pin: '<path d="M9 4h6l-1 6 3 3H7l3-3z"></path><path d="M12 13v7"></path>',
};
let view = "case";
let tab = "keep";
let exportFormat = "text";

function iconButton(name, label, onClick, pressed) {
  const b = document.createElement("button");
  b.setAttribute("aria-label", label);
  b.title = label;
  if (pressed !== undefined) b.setAttribute("aria-pressed", String(pressed));
  b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`; // fixed markup, no data
  b.addEventListener("click", onClick);
  return b;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function inTab(item) {
  if (tab === "findings") return item.star;
  return item.disposition === tab;
}

function renderItem(item) {
  const li = el("li", item.star ? "item finding" : "item");
  const head = el("div", "item-head");
  head.append(el("span", "time", item.time), el("span", "tag", item.label));
  const reason = REASONS[item.reason] || (item.negative ? REASONS.negative_finding : "");
  if (reason) head.append(el("span", "reason", reason));
  if (item.unlabelled) head.append(el("span", "reason", "Not labelled"));

  const act = (fn) => async () => render(await fn());
  const actions = el("span", "item-actions");
  actions.append(iconButton("star", item.star ? "Remove from findings" : "Mark as a finding", act(() => api().star_item(item.ids, !item.star)), item.star));
  actions.append(iconButton("comment", "Comment", () => editComment(li, item)));
  if (item.kind === "screenshot") {
    actions.append(iconButton("pin", item.pinned ? "Leave out of the export" : "Include in the export", act(() => api().pin_item(item.ids, !item.pinned)), item.pinned));
  }
  if (item.disposition === "keep") actions.append(iconButton("hide", "Hide", act(() => api().decide_item(item.ids, "hide"))));
  if (item.disposition === "hide") actions.append(iconButton("restore", "Restore", act(() => api().decide_item(item.ids, "keep"))));
  head.append(actions);
  li.append(head);

  if (item.text) li.append(el("div", "item-text", item.kind === "screenshot" ? `${item.text} · ${item.trigger}` : item.text));
  if (item.code) li.append(el("pre", "code", item.code));
  if (item.summary) li.append(el("div", "summary", item.summary));
  if (item.annotation) li.append(el("div", "comment", `Comment: ${item.annotation}`));

  if (item.disposition === "review") {
    const decide = el("div", "decide");
    for (const value of item.suggest || []) {
      const add = el("button", "outline", `+ ${value}`);
      add.setAttribute("aria-label", `Add ${value} as a case entity`);
      add.addEventListener("click", act(() => api().add_entity(value)));
      decide.append(add);
    }
    const keep = el("button", "outline", "Keep");
    keep.addEventListener("click", act(() => api().decide_item(item.ids, "keep")));
    const hide = el("button", "outline", "Hide");
    hide.addEventListener("click", act(() => api().decide_item(item.ids, "hide")));
    decide.append(keep, hide);
    li.append(decide);
  }
  return li;
}

function editComment(li, item) {
  const input = el("input", "comment-input");
  input.value = item.annotation || "";
  input.setAttribute("aria-label", "Comment");
  input.placeholder = "Why this matters";
  input.addEventListener("keydown", async (e) => {
    if (e.key === "Enter") render(await api().comment_item(item.ids, input.value));
    if (e.key === "Escape") renderTimeline(true);
  });
  li.querySelector(".comment")?.remove();
  li.append(input);
  input.focus();
}

function renderTimeline(force = false) {
  const list = $(".timeline");
  const typing = list.contains(document.activeElement) && document.activeElement.tagName === "INPUT";
  if (typing && !force) return;
  const items = state.timeline.filter(inTab);
  list.replaceChildren(...items.map(renderItem));
  if (!items.length) list.append(el("li", "timeline-empty", tab === "keep" ? "Nothing kept yet." : "Nothing here."));
}

function renderTabs() {
  const counts = state.case.counts;
  const n = { keep: counts.keep, findings: counts.findings, review: counts.review, hide: counts.hide };
  for (const b of document.querySelectorAll("[data-tab]")) {
    b.setAttribute("aria-pressed", String(b.dataset.tab === tab));
    b.querySelector(".tab-count").textContent = n[b.dataset.tab];
  }
  $(".tab-help").hidden = !TAB_HELP[tab];
  $(".tab-help").textContent = TAB_HELP[tab] || "";
}

// Called at the end of renderCase.
function renderTimelineArea() {
  const c = state.case;
  for (const sel of [".tabs", ".timeline", ".case-footer"]) $(sel).hidden = !c;
  const depth = c?.labelling || 0;
  $(".labelling").hidden = !depth;
  $(".labelling").textContent = depth === 1 ? "Labelling 1 event" : `Labelling ${depth} events`;
  if (!c) {
    $(".tab-help").hidden = true;
    if (view === "export") setView("case");
    return;
  }
  renderTabs();
  renderTimeline();
  if (view === "export") refreshPreview();
}

document.addEventListener("click", (event) => {
  const b = event.target.closest("[data-tab]");
  if (!b || !state?.case) return;
  tab = b.dataset.tab;
  renderTabs();
  renderTimeline(true);
});

$(".note-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("#note");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  render(await api().add_note(text));
});

// Views

function setView(name) {
  view = name;
  for (const v of ["case", "export", "cases", "settings"]) $(`.view-${v}`).hidden = v !== name;
  if (name === "export") refreshPreview();
  if (name === "cases") loadCases();
  if (name === "settings") loadSettings();
}

document.addEventListener("click", (event) => {
  const b = event.target.closest("[data-view]");
  if (!b || !state) return;
  if (b.dataset.view === "export" && !state.case) return;
  setView(b.dataset.view);
});

// Export (FR-27, FR-28)

function exportForm() {
  const form = { fmt: exportFormat };
  for (const input of document.querySelectorAll(".include input")) form[input.name] = input.checked;
  return form;
}

let previewPending = false;
async function refreshPreview() {
  if (previewPending || !state?.case) return;
  previewPending = true;
  try {
    const p = await api().export_preview(exportForm());
    $(".preview").textContent = p.text;
    const id = state.case.incidentId || "Manual case";
    $(".export-meta").textContent = `${id} · ${p.kept} kept · ${p.findings} ${p.findings === 1 ? "finding" : "findings"}`;
    $(".rows-label").textContent = `Top ${p.rowLimit} result rows`;
    const zip = $('[data-export="screenshots"]');
    zip.textContent = `Screenshots (.zip, ${p.screenshots})`;
    zip.disabled = p.screenshots === 0;
  } finally {
    previewPending = false;
  }
}

document.addEventListener("click", async (event) => {
  const f = event.target.closest("[data-fmt]");
  if (f) {
    exportFormat = f.dataset.fmt;
    for (const b of document.querySelectorAll("[data-fmt]")) b.setAttribute("aria-checked", String(b === f));
    refreshPreview();
    return;
  }
  const b = event.target.closest("[data-export]");
  if (!b) return;
  const status = $(".export-status");
  if (b.dataset.export === "copy") {
    await api().export_copy(exportForm());
    status.textContent = "Copied. The case is marked as exported.";
  } else if (b.dataset.export === "save") {
    const path = await api().export_save(exportForm());
    status.textContent = path ? `Saved to ${path}` : "";
  } else {
    const path = await api().export_screenshots();
    status.textContent = path ? `Screenshots saved to ${path}` : "";
  }
});
$(".include").addEventListener("change", refreshPreview);

// Cases (FR-29 to FR-32)

function megabytes(bytes) {
  return bytes < 1e6 ? `${Math.max(1, Math.round(bytes / 1e3))} KB` : `${(bytes / 1e6).toFixed(1)} MB`;
}

function when(ts) {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

function renderCases(s) {
  $(".cases-meta").textContent = `Keeping the last ${s.limit} · ${megabytes(s.bytes)} on disk`;
  const act = (fn) => async () => renderCases(await fn());

  $(".confirm-box").hidden = !s.awaitingConfirmation.length;
  $(".confirm-list").replaceChildren(...s.awaitingConfirmation.map((c) => {
    const li = el("li");
    li.append(el("span", "grow", c.title || c.incidentId || c.id));
    const del = el("button", "outline small", "Delete");
    del.addEventListener("click", act(() => api().delete_case(c.id)));
    const keep = el("button", "outline small", "Keep");
    keep.setAttribute("aria-label", `Keep ${c.title || c.id} and pin it`);
    keep.addEventListener("click", act(() => api().keep_case(c.id)));
    li.append(del, keep);
    return li;
  }));

  $(".case-list").replaceChildren(...s.cases.map((c) => {
    const li = el("li", "case-row");
    const head = el("div", "row-head");
    head.append(el("span", "mono", c.incidentId || "Manual"));
    if (c.active) head.append(el("span", "badge live", "Recording"));
    head.append(el("span", c.exported ? "badge exported" : "badge", c.exported ? "Exported" : "Not exported"));
    if (c.pinned) head.append(el("span", "badge", "Pinned"));
    const actions = el("span", "row-actions");
    const pin = el("button", "", c.pinned ? "Unpin" : "Pin");
    pin.setAttribute("aria-pressed", String(Boolean(c.pinned)));
    pin.addEventListener("click", act(() => api().pin_case(c.id, !c.pinned)));
    actions.append(pin);
    if (!c.active) {
      const open = el("button", "", "Open");
      open.addEventListener("click", async () => {
        render(await api().open_case(c.id));
        setView("case");
      });
      const del = el("button", "", "Delete");
      del.addEventListener("click", async () => {
        if (c.exported || del.dataset.confirm) return renderCases(await api().delete_case(c.id));
        del.dataset.confirm = "1";
        del.textContent = "Not exported. Delete?";
      });
      actions.append(open, del);
    }
    head.append(actions);
    li.append(head, el("div", "title", c.title || "Untitled case"));
    const meta = [`Last active ${when(c.lastActivity)}`, `${c.events} events`];
    if (c.exportedAt) meta.push(`exported ${when(c.exportedAt)}`);
    li.append(el("div", "meta", meta.join(" · ")));
    if (c.id === s.nextToGo) li.append(el("div", "meta next", "Deleted when the next case starts"));
    return li;
  }));
}

async function loadCases() {
  renderCases(await api().cases_state());
}

// Settings

const SHORTCUTS = {
  note: ["Ctrl+Alt+N", "Add a note"],
  record: ["Ctrl+Alt+S", "Start a case, or pause and resume"],
  panel: ["Ctrl+Alt+I", "Show or collapse the panel"],
};

let settings = null;

function renderSettings(s) {
  settings = s;
  $(".settings-listener").textContent = listenerText(state.listener);
  for (const b of document.querySelectorAll("button[data-setting]")) b.setAttribute("aria-checked", String(s[b.dataset.setting] === b.dataset.value));
  for (const input of document.querySelectorAll("input[data-setting]")) {
    if (document.activeElement === input) continue;
    if (input.type === "checkbox") input.checked = input.dataset.on ? s[input.dataset.setting] === input.dataset.on : Boolean(s[input.dataset.setting]);
    else input.value = s[input.dataset.setting];
  }
  $(".interval-on").checked = s.interval_seconds > 0;
  if (document.activeElement !== $(".interval-seconds")) $(".interval-seconds").value = s.interval_seconds || 60;
  $(".shortcuts").replaceChildren(...Object.values(SHORTCUTS).map(([keys, what]) => {
    const li = el("li");
    const held = s.shortcutsUnavailable.includes(keys);
    li.append(el("span", "mono", keys), el("span", held ? "held" : "", held ? `${what} (held by another program, so off)` : what));
    return li;
  }));
  $(".desktop-apps").replaceChildren(...s.desktop_apps.map((app) => {
    const li = el("li");
    const actions = el("span", "row-actions");
    const remove = el("button", "", "Remove");
    remove.setAttribute("aria-label", `Stop capturing ${app}`);
    remove.addEventListener("click", () => saveSetting({ desktop_apps: settings.desktop_apps.filter((a) => a !== app) }));
    actions.append(remove);
    li.append(el("span", "mono", app), actions);
    return li;
  }));
}

// Programs with a window open now, for the desktop allow list.
async function loadOpenApps() {
  const allowed = new Set((settings?.desktop_apps ?? []).map((a) => a.toLowerCase()));
  const apps = (await api().desktop_open_apps()).filter(({ app }) => !allowed.has(app.toLowerCase()));
  $(".app-picker").replaceChildren(...apps.map(({ app, title }) => {
    const option = el("option", "", `${app} (${title})`);
    option.value = app;
    return option;
  }));
  $('[data-desktop="add"]').disabled = apps.length === 0;
}

async function loadSettings() {
  renderSettings(await api().get_settings());
  await loadOpenApps();
}

async function saveSetting(changes) {
  renderSettings(await api().update_settings(changes));
  render(await api().get_state());
}

$(".view-settings").addEventListener("click", async (event) => {
  const b = event.target.closest("button[data-setting]");
  if (b) saveSetting({ [b.dataset.setting]: b.dataset.value });
  if (event.target.closest('[data-desktop="add"]') && $(".app-picker").value) {
    await saveSetting({ desktop_apps: [...settings.desktop_apps, $(".app-picker").value] });
    await loadOpenApps();
  }
});
$(".app-picker").addEventListener("focus", loadOpenApps);
$(".view-settings").addEventListener("change", (event) => {
  const input = event.target;
  if (input.classList.contains("interval-on") || input.classList.contains("interval-seconds")) {
    const seconds = Number($(".interval-seconds").value) || 60;
    saveSetting({ interval_seconds: $(".interval-on").checked ? seconds : 0 });
    return;
  }
  const name = input.dataset.setting;
  if (!name) return;
  if (input.type === "checkbox") {
    saveSetting({ [name]: input.dataset.on ? (input.checked ? input.dataset.on : input.dataset.off) : input.checked });
  } else if (input.value !== "") {
    saveSetting({ [name]: Math.round(Number(input.value)) });
  }
});

// Called from Python by the global shortcuts.

function focusNote() {
  if (!state?.case) return openStartForm();
  setView("case");
  $("#note").focus();
}

function openStartForm() {
  setView("case");
  if (!state?.case) caseActions.open_form();
}
