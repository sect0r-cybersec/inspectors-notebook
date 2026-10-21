// Copies the browser API polyfill next to the extension source, so the extension
// loads only local files.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const target = join(here, "..", "src", "vendor");
mkdirSync(target, { recursive: true });
copyFileSync(
  require.resolve("webextension-polyfill/dist/browser-polyfill.min.js"),
  join(target, "browser-polyfill.min.js"),
);
