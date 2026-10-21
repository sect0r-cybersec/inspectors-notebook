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
