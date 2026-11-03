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
import { decodePng } from "./pixels.mjs";

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
export async function openPage({
  query = "",
  gate = "BROWSER_TEST",
  waitFor = "Boolean(window.ex)",
  /**
   * §168: the bitmap is only comparable across runs if the viewport is. The Chrome window defaults
   * to whatever the OS gives it (764x485 here), and DPI changes `deviceScaleFactor` -- so a pixel
   * gate that does not pin these is measuring the machine, not the page.
   */
  viewport = null,
} = {}) {
  const fail = (message) => {
    console.error(`${gate} FAIL: ${message}`);
    process.exit(1);
  };

  let port = 0;
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
  // §188: `listen(0)` asks the OS for any free port, and undici (Node's fetch) **refuses a list of
  // well-known ports** ("bad port": 6000, 6666, 10080, ...). One run of the gate got one of those and
  // failed with `TypeError: fetch failed [cause]: bad port` -- a red gate that had nothing to do with
  // the content. So: ask for 0, and if the OS hands back a port undici blocks, ask again.
  const BLOCKED_PORTS = new Set([1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69,
    77, 79, 87, 95, 101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 137, 139, 143,
    161, 179, 389, 427, 465, 512, 513, 514, 515, 526, 530, 531, 532, 540, 548, 554, 556, 563, 587,
    601, 636, 989, 990, 993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 4190, 5060, 5061, 6000, 6566,
    6665, 6666, 6667, 6668, 6669, 6679, 6697, 10080]);
  for (;;) {
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const candidate = server.address().port;
    if (!BLOCKED_PORTS.has(candidate)) {
      port = candidate;
      break;
    }
    await new Promise((resolve) => server.close(resolve));
  }

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

  /**
   * §165: press a button with **real** pointer events, and report what the click would hit.
   *
   * `element.dispatchEvent(new MouseEvent(...))` (what every earlier scenario used) bypasses
   * hit-testing completely: a button that a modal covers, or that is scrolled out of view, still
   * "works". That is precisely the class of bug a page test must not be blind to. So this scrolls
   * the element into view, asks `elementFromPoint` what is actually on top of the centre, and then
   * sends `mousePressed`/`mouseReleased` at that point.
   *
   * Returns the hit-test verdict so the caller can assert on it:
   * `{ missing, x, y, hits, coverTag }` — `hits: false` means something else is on top.
   */
  async function probe(selector, index = 0) {
    return evaluate(`(() => {
      const node = document.querySelectorAll(${JSON.stringify(selector)})[${index}];
      if (!node) return null;
      node.scrollIntoView({ block: "center", inline: "center" });
      const r = node.getBoundingClientRect();
      const x = r.left + r.width / 2;
      const y = r.top + r.height / 2;
      const top = document.elementFromPoint(x, y);
      return {
        x: x, y: y, width: r.width, height: r.height,
        hits: !!top && (top === node || node.contains(top)),
        coverTag: top ? (top.id ? "#" + top.id : String(top.className || top.tagName)) : null,
      };
    })()`).then((box) => (box === null ? { missing: true, selector: selector, index: index } : box));
  }

  /**
   * Press a button with **real** pointer events, once it is actually hit-testable.
   *
   * `element.dispatchEvent(new MouseEvent(...))` (what every earlier scenario used) bypasses
   * hit-testing completely: a button that a modal covers, or that is scrolled out of view, still
   * "works". That is precisely the class of bug a page test must not be blind to.
   *
   * The wait matters as much as the hit test: a CSS transition leaves the box hit-testable a frame
   * or two after `hidden` goes false, and clicking during that window looks exactly like "the button
   * is covered" (it happened on `#modalClose`). So this polls until `hits` is true, and reports the
   * **last** probe either way -- a genuinely covered button still comes back with `hits: false`.
   */
  async function clickSelector(selector, index = 0, budgetMs = 2000) {
    let box = await probe(selector, index);
    if (box.missing || box.empty) return box;
    const until = Date.now() + budgetMs;
    while (box.hits !== true && Date.now() < until) {
      await new Promise((resolve) => setTimeout(resolve, 25));
      box = await probe(selector, index);
      if (box.missing || box.empty) return box;
    }
    if (!(box.width > 0 && box.height > 0)) {
      return { ...box, empty: true };
    }
    await clickAt(box.x, box.y);
    return box;
  }

  /**
   * Press at **exactly these coordinates**, with no hit test and no waiting.
   *
   * The partner of `probe`: when the point of the test is that the click must land on whatever is on
   * top (a modal swallowing a click meant for the map), waiting for the target to become hit-testable
   * would silently turn the test into a different one.
   */
  async function clickAt(x, y) {
    await send("Input.dispatchMouseEvent", {
      type: "mouseMoved", x: x, y: y, buttons: 0,
    });
    await send("Input.dispatchMouseEvent", {
      type: "mousePressed", x: x, y: y, button: "left", buttons: 1, clickCount: 1,
    });
    await send("Input.dispatchMouseEvent", {
      type: "mouseReleased", x: x, y: y, button: "left", buttons: 0, clickCount: 1,
    });
  }

  /** §165: type into a field the way a person does — focus it with a real click, then insert text. */
  async function typeInto(selector, text) {
    const box = await clickSelector(selector);
    if (box.missing) return box;
    // Clear first: `Input.insertText` inserts at the caret, and the seed field starts empty only
    // until somebody has typed in it.
    await evaluate(
      "(() => { const field = document.querySelector(" + JSON.stringify(selector) +
        "); if (field) { field.value = ''; field.focus(); } })()"
    );
    await send("Input.insertText", { text: text });
    const value = await evaluate(
      "(() => { const field = document.querySelector(" + JSON.stringify(selector) +
        "); return field ? field.value : null; })()"
    );
    return { ...box, value: value };
  }

  await send("Runtime.enable");
  await send("Page.enable");
  if (viewport) {
    await send("Emulation.setDeviceMetricsOverride", {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: 1,
      mobile: false,
    });
  }

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
    send,
    /**
     * §168: the page as the rasterizer saw it, decoded to RGBA. `Page.captureScreenshot` hands back
     * base64 PNG; `decodePng` turns it into pixels so assertions can be about **the picture** --
     * which is the one thing a DOM assertion cannot check.
     */
    async screenshot(rect = null) {
      const params = { format: "png", fromSurface: true, captureBeyondViewport: false };
      if (rect) {
        params.clip = { ...rect, scale: 1 };
      }
      const shot = await send("Page.captureScreenshot", params);
      return decodePng(Buffer.from(shot.data, "base64"));
    },
    evaluate,
    probe,
    clickAt,
    clickSelector,
    typeInto,
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
