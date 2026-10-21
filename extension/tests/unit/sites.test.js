// consoles.js is a classic script with top-level declarations, so run it in its own context.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

function load() {
  const context = vm.createContext({ URL });
  vm.runInContext(readFileSync(new URL("../../src/consoles.js", import.meta.url), "utf8"), context);
  return context;
}

test("shipped consoles are always listened to", () => {
  const c = load();
  assert.equal(vm.runInContext('consoleFor("https://security.microsoft.com/incidents")?.id', c), "defender");
  assert.equal(vm.runInContext('consoleFor("https://tickets.example.com/")', c), null);
  assert.deepEqual([...vm.runInContext("consolePatterns()", c)], ["https://security.microsoft.com/*", "https://portal.azure.com/*"]);
});

test("added sites are listened to under their host name", () => {
  const c = load();
  vm.runInContext('setAddedSites(["https://tickets.example.com", "https://security.microsoft.com"])', c);
  const site = vm.runInContext('consoleFor("https://tickets.example.com/browse/SOC-1")', c);
  assert.deepEqual({ ...site }, { id: "tickets.example.com", name: "tickets.example.com", origin: "https://tickets.example.com", added: true });
  // A shipped console added again is not duplicated or marked as added.
  assert.equal(vm.runInContext('consoleFor("https://security.microsoft.com/")?.added', c), undefined);
  assert.equal(vm.runInContext("consolePatterns().length", c), 3);
  vm.runInContext("setAddedSites([])", c);
  assert.equal(vm.runInContext('consoleFor("https://tickets.example.com/")', c), null);
});
