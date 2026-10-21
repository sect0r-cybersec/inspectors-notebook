"use strict";

const $ = (selector) => document.querySelector(selector);

function plural(n, word) {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function render(s) {
  const connected = s.app === "connected";
  $(".closed").hidden = s.app !== "closed";
  $(".unavailable").hidden = s.app !== "unavailable";
  $(".connected").hidden = !connected;

  $(".app-status").classList.toggle("ok", connected);
  $(".app-text").textContent = connected ? "Connected" : s.app === "unavailable" ? "Not installed" : "App closed";

  $(".listening").textContent =
    `Listening in ${plural(s.listening, "console tab")}. Nothing is recorded until the Inspector app is open.`;
  $('[data-action="set_open_on_console"]').checked = s.openOnConsole;

  $(".tab-text").textContent = !s.tab
    ? "Not a console tab · not captured"
    : `${s.tab.console} · ${s.tab.paused ? "paused" : "capturing"}`;
  $(".pause").hidden = !s.tab;
  $('[data-action="set_paused"]').checked = Boolean(s.tab?.paused);

  // Any HTTPS site can be added; the consoles that ship with the extension cannot be removed.
  const site = s.site;
  $(".site").hidden = !site || (site.listened && !site.added);
  if (site) {
    const host = new URL(site.origin).hostname;
    $(".site-text").textContent = site.listened ? `${host} · listening` : `${host} · not listening`;
    $('[data-site="add"]').hidden = site.listened;
    $('[data-site="remove"]').hidden = !site.added;
  }
  state = s;
}

let state = null;

async function refresh() {
  render(await browser.runtime.sendMessage({ type: "popup_state" }));
}

document.addEventListener("click", async (event) => {
  const siteButton = event.target.closest("button[data-site]");
  if (siteButton && state?.site) {
    const origin = state.site.origin;
    if (siteButton.dataset.site === "add") {
      // Must be the first await in the click, so the browser sees the user's gesture.
      const granted = await browser.permissions.request({ origins: [`${origin}/*`] });
      if (granted) await browser.runtime.sendMessage({ type: "add_site", origin });
    } else {
      await browser.runtime.sendMessage({ type: "remove_site", origin });
    }
    refresh();
    return;
  }
  const el = event.target.closest("button[data-action]");
  if (!el) return;
  await browser.runtime.sendMessage({ type: el.dataset.action });
  if (el.dataset.action === "open_app" && state?.app === "connected") window.close();
});

document.addEventListener("change", async (event) => {
  const el = event.target;
  if (el.dataset.action === "set_paused") {
    await browser.runtime.sendMessage({ type: "set_paused", tabId: state.tab.id, paused: el.checked });
  } else if (el.dataset.action === "set_open_on_console") {
    await browser.runtime.sendMessage({ type: "set_open_on_console", value: el.checked });
  }
  refresh();
});

refresh();
// The app may start or stop while the popup is open.
setInterval(refresh, 1000);
