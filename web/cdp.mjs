// A **real browser** page, with no dependencies (§151).
//
// Why not Playwright: `web/` is deliberately zero-build, and Playwright would pull a second copy of
// Chromium (~150 MB). Chrome is already installed, and Node 22 has a built-in `WebSocket`, so the
// whole driver is: a static server (node:http), a headless Chrome (CDP), and a script evaluated in
// the page.
//
// Extracted from `browser_test.mjs` when the soak test (§151) needed the same plumbing. One copy of
// "launch a browser and talk CDP" is the point: two copies drift, and the second one drifts silently
// (it only runs inside a gate that most changes do not touch).

import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL("./", import.meta.url));
const ROOT = normalize(join(HERE, ".."));
const CHROME_CANDIDATES = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
];
const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".wasm": "application/wasm",
  ".json": "application/json",
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Serve `web/` (and the rest of the tree, so `../kernel/target/...` fallbacks resolve), launch a
 * headless Chrome, navigate to `index.html?<query>` and return a handle.
 *
 * `handle.evaluate(expression)` runs the expression in the page (promises awaited, value returned).
 * `handle.close()` tears everything down. `handle.fail` prints the gate's own failure prefix.
 */
export async function openPage({ query = "", gate = "BROWSER_TEST", waitFor = "Boolean(window.ex)" } = {}) {
  const fail = (message) => {
    console.error(`${gate} FAIL: ${message}`);
    process.exit(1);
  };

  const server = createServer(async (req, res) => {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const file = normalize(join(ROOT, path));
    if (!file.startsWith(ROOT)) {
      res.writeHead(403).end();
      return;
    }
    try {
      const body = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] || "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  // A fixed port would collide with a dev server the user is running; 0 asks the OS.
  const port = server.address().port;

  const chromePath = await (async () => {
    for (const candidate of CHROME_CANDIDATES) {
      try {
        await readFile(candidate);
        return candidate;
      } catch {
        /* keep looking */
      }
    }
    return null;
  })();
  if (!chromePath) fail("no Chrome or Edge found");

  const profile = await mkdtemp(join(tmpdir(), "rd-browser-"));
  const chrome = spawn(chromePath, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--mute-audio",
    `--user-data-dir=${profile}`,
    "--remote-debugging-port=0",
    "about:blank",
  ], { stdio: "ignore" });

  let devtoolsPort = 0;
  for (let i = 0; i < 150; i++) {
    try {
      const text = await readFile(join(profile, "DevToolsActivePort"), "utf8");
      devtoolsPort = Number(text.split("\n")[0]);
      if (devtoolsPort > 0) break;
    } catch {
      /* not written yet */
    }
    await sleep(100);
  }
  if (!devtoolsPort) fail("Chrome never opened its devtools port");

  const targets = await (await fetch(`http://127.0.0.1:${devtoolsPort}/json/list`)).json();
  const target = targets.find((t) => t.type === "page");
  if (!target) fail("Chrome has no page target");

  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", () => reject(new Error("CDP socket failed")), { once: true });
  });

  let nextId = 1;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    const waiter = pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id);
    if (message.error) waiter.reject(new Error(JSON.stringify(message.error)));
    else waiter.resolve(message.result);
  });
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });

  /** Evaluate `expression` in the page and return the value (promises awaited). */
  async function evaluate(expression) {
    const result = await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      fail(
        "the page script threw: " +
          (result.exceptionDetails.exception?.description || result.exceptionDetails.text)
      );
    }
    return result.result.value;
  }

  await send("Runtime.enable");
  await send("Page.enable");

  const suffix = query ? `?${query}` : "";
  const loaded = await send("Page.navigate", {
    url: `http://127.0.0.1:${port}/web/index.html${suffix}`,
  });
  if (loaded.errorText) fail(`navigation failed: ${loaded.errorText}`);

  let ready = false;
  for (let i = 0; i < 100; i++) {
    ready = await evaluate(waitFor);
    if (ready) break;
    await sleep(100);
  }
  if (!ready) fail(`the page never became ready (waited for ${waitFor})`);

  return {
    evaluate,
    fail,
    port,
    async close() {
      socket.close();
      chrome.kill();
      server.close();
      await rm(profile, { recursive: true, force: true }).catch(() => {});
    },
  };
}
