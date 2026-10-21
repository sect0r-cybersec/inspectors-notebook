// S2 round-trip test in Firefox, run through web-ext with a throwaway profile.
// Playwright's Firefox cannot load extensions, so this checks the round trip from
// the companion's side. Needs the relay registered and the companion closed.
import { execFileSync } from "node:child_process";
import webExt from "web-ext";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { FakeCompanion } from "./fake-companion.js";

const EXTENSION = resolve(dirname(fileURLToPath(import.meta.url)), "..", "src");
const FIREFOX = process.env.FIREFOX_PATH ?? "C:\\Program Files\\Mozilla Firefox\\firefox.exe";

// web-ext kills the Firefox process it started, but Firefox on Windows can hand over
// to another process that keeps running; stop anything still using the test profile.
function stopFirefoxUsing(profileDir) {
  const script = `Get-CimInstance Win32_Process -Filter "Name='firefox.exe'" | ` +
    `Where-Object { $_.CommandLine -like '*${profileDir.replaceAll("'", "''")}*' } | ` +
    `ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`;
  execFileSync("powershell", ["-NoProfile", "-Command", script]);
}

const fake = await FakeCompanion.start();
let runner;
let failed = false;
try {
  runner = await webExt.cmd.run(
    {
      sourceDir: EXTENSION,
      target: ["firefox-desktop"],
      firefox: FIREFOX,
      args: ["--headless"],
      noReload: true,
      noInput: true,
      startUrl: ["about:blank"],
    },
    { shouldExitProgram: false },
  );
  await fake.waitFor((m) => m.type === "hello" && m.browser === "firefox", 60_000);
  // Sent only after the companion's reply reaches the extension: the full round trip.
  await fake.waitFor((m) => m.type === "tabs" && m.count === 0);
  console.log("PASS firefox: hello and tab count round-trip through relay and companion");
} catch (e) {
  failed = true;
  console.error("FAIL firefox:", e.message);
} finally {
  const profileDir = runner?.extensionRunners?.[0]?.profile?.path();
  await runner?.exit();
  if (profileDir) stopFirefoxUsing(profileDir);
  await fake.stop();
}
process.exit(failed ? 1 : 0);
