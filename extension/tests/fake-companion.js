// Runs tests/fake_companion.py and collects what it receives from the relay.
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export class FakeCompanion {
  messages = [];

  static async start({ recording = false, interval = 0 } = {}) {
    const fake = new FakeCompanion();
    const args = ["run", "--no-sync", "python", "extension/tests/fake_companion.py"];
    if (recording) args.push("--recording");
    if (interval) args.push(`--interval=${interval}`);
    fake.proc = spawn("uv", args, {
      cwd: REPO,
      stdio: ["pipe", "pipe", "inherit"],
    });
    fake.exited = new Promise((done) => fake.proc.on("exit", done));
    createInterface({ input: fake.proc.stdout }).on("line", (line) => fake.messages.push(JSON.parse(line)));
    const first = await fake.waitFor((m) => "fake" in m, 30_000);
    if (first.fake !== "ready") {
      throw new Error("The companion pipe is already in use. Close Inspector's Notebook before running these tests.");
    }
    return fake;
  }

  async waitFor(predicate, timeout = 15_000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const found = this.messages.find(predicate);
      if (found) return found;
      await new Promise((r) => setTimeout(r, 50));
    }
    throw new Error(`Timed out waiting for a message. Received: ${JSON.stringify(this.messages)}`);
  }

  async stop() {
    this.proc.stdin.end();
    await this.exited;
  }
}
