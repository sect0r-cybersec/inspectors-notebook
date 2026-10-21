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
