// A **real browser** regression, with no dependencies.
//
// Why not Playwright: `web/` is deliberately zero-build, and Playwright would pull a second copy of
// Chromium (~150 MB). Chrome is already installed, and Node 22 has a built-in `WebSocket`, so the
// whole driver is: a static server (node:http), a headless Chrome (CDP), and a script evaluated in
// the page. That is enough for what this file asserts -- **key text must appear**, no pixels.
//
// What it covers (the flows that kept breaking by hand):
//   * the tower blessing is offered and taking one settles the run;
//   * the map refuses an unreachable node **and says why**;
//   * a fight starts, a card is played, and the battle log names the card and its effect;
//   * the top bar shows `幕 N` and tracks the fight's health;
//   * an unaffordable card is marked `unaffordable` once the energy is gone;
//   * Shift+click opens the card detail.
//
// Run: node web/browser_test.mjs   (exit 0 and `BROWSER_TEST PASS` = green)

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

const fail = (message) => {
  console.error("BROWSER_TEST FAIL: " + message);
  process.exit(1);
};
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ---- 1. a static server for the tree ---------------------------------------------------------
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
const port = server.address().port;

// ---- 2. headless Chrome, over CDP ------------------------------------------------------------
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
const chrome = spawn(
  chromePath,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--mute-audio",
    `--user-data-dir=${profile}`,
    "--remote-debugging-port=0",
    "about:blank",
  ],
  { stdio: "ignore" }
);

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

// ---- 3. the flow ------------------------------------------------------------------------------
// The query carries **debug** because the potion scenario (§150) pins a seed through RD_DEBUG.
const url = `http://127.0.0.1:${port}/web/index.html?browser-test&debug`;
const loaded = await send("Page.navigate", { url });
if (loaded.errorText) fail(`navigation failed: ${loaded.errorText}`);

// Wait for `ex` and the blessing panel -- the page fetches and instantiates the wasm first.
let ready = false;
for (let i = 0; i < 100; i++) {
  ready = await evaluate('Boolean(window.ex && document.querySelector("#nodePanel [data-panel-action]"))');
  if (ready) break;
  await sleep(100);
}
if (!ready) fail("the page never offered a tower blessing");

const report = await evaluate(`(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const panel = () => document.getElementById("nodePanel");
  const text = (el) => el.innerText.replace(/\\s+/g, " ").trim();
  const logLines = () => document.getElementById("log").innerText.split("\\n").filter((l) => l.trim());
  const out = {};
  // The observation comes through a buffer, not a getter (same idiom as index.html).
  const buf = ex.rd_env_scratch_buf();
  const cell = (index) => {
    ex.rd_env_observe_into(buf);
    return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[index];
  };

  // (a) the blessing is a choice, with a name rather than an id
  out.blessings = [...panel().querySelectorAll("[data-panel-action]")]
    .map((b) => text(b))
    .filter(Boolean);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  // a card blessing owes a pick; take it so the run can move
  if (ex.rd_run_pending() === 7) {
    const pick = panel().querySelector("[data-panel-action]");
    if (pick) { pick.click(); await sleep(0); }
    const card = document.querySelector("#modalBody [data-pick]");
    if (card) { card.click(); await sleep(0); }
  }
  out.afterBlessing = { pending: ex.rd_run_pending(), floor: ex.rd_run_observe(0) };

  // (b) an unreachable node: refuses and says why
  const unlit = [...document.querySelectorAll("#mapbox g.node:not(.reachable):not(.here)")][0];
  if (unlit) {
    unlit.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(0);
  }
  out.refusal = text(document.getElementById("msg"));

  // (c) walk into a fight and start it
  const lit = [...document.querySelectorAll("#mapbox g.node.reachable")];
  if (lit.length) {
    lit[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(0);
  }
  const fight = panel().querySelector("[data-panel-action]");
  if (fight) { fight.click(); await sleep(0); }
  out.fight = { inFight: !document.getElementById("handPanel").hidden, energy: cell(8) };

  // (d) Shift+click a card: the detail modal must name it and show its text
  const card = document.querySelector("#hand button.card");
  if (card) {
    card.dispatchEvent(new MouseEvent("click", { bubbles: true, shiftKey: true }));
    await sleep(0);
    out.card = {
      open: !document.getElementById("modal").hidden,
      title: document.getElementById("modalTitle").innerText.trim(),
      body: text(document.getElementById("modalBody")).slice(0, 60),
    };
    document.getElementById("modal").hidden = true;
  }

  // (e) play every affordable card, then look at the log and the top bar
  for (let i = 0; i < 6; i++) {
    const next = [...document.querySelectorAll("#hand button.card:not([disabled])")][0];
    if (!next) break;
    next.click();
    await sleep(0);
    const target = document.querySelector("#enemies [data-target-slot]");
    if (target) { target.click(); await sleep(0); }
  }
  out.log = logLines().slice(-3);
  out.topBar = text(document.getElementById("runStats"));
  out.energyAfter = cell(8);
  out.unaffordable = document.querySelectorAll("#hand button.card.unaffordable").length;

  // (f) **A potion must be usable from the belt** (§150). This is the scenario that was missing:
  // a handler that throws is a dead button, and nothing above clicked one. It found a real
  // regression -- renderTopBar had a local named act (ex.rd_run_act()), which shadowed the page's
  // act(call, label) helper, so the button threw TypeError: act is not a function.
  //
  // The seed is pinned because a potion drop is 40%: this checks the **wiring**, not the drop.
  // If a content change ever moves the drop, pick another seed with a comment.
  const POTION_SEED = 12;
  const finishFight = async () => {
    for (let step = 0; step < 80; step++) {
      const inFight = !document.getElementById("handPanel").hidden;
      if (!inFight) break;
      const next = document.querySelector("#hand button.card:not([disabled])");
      if (next) {
        next.click();
        await sleep(0);
        const target = document.querySelector("#enemies [data-target-slot]");
        if (target) { target.click(); await sleep(0); }
      } else {
        document.getElementById("endTurn").click();
        await sleep(0);
      }
    }
  };
  const walkIntoFight = async () => {
    for (let step = 0; step < 20; step++) {
      if (!document.getElementById("handPanel").hidden) return true;
      const lit = [...document.querySelectorAll("#mapbox g.node.reachable")];
      if (!lit.length) return false;
      lit[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await sleep(0);
      const first = panel().querySelector("[data-panel-action]");
      if (first) first.click();
      await sleep(0);
      if (document.getElementById("handPanel").hidden) {
        const leave = [...panel().querySelectorAll("[data-panel-action]")]
          .find((b) => b.innerText.includes("离开"));
        if (leave) { leave.click(); await sleep(0); }
      }
    }
    return !document.getElementById("handPanel").hidden;
  };

  window.RD_DEBUG.startWithSeed(POTION_SEED);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  await walkIntoFight();
  await finishFight();
  out.potionBeltBefore = ex.rd_run_potion_count();
  if (ex.rd_run_pending() === 4) {
    const row = [...panel().querySelectorAll(".shop-item")].find((r) => r.innerText.includes("药水"));
    if (row) {
      const takeButton = row.querySelector("[data-panel-action]");
      if (takeButton) { takeButton.click(); await sleep(0); }
    }
    const skip = [...panel().querySelectorAll("[data-panel-action]")].pop();
    if (skip) { skip.click(); await sleep(0); }
  }
  out.potionInBelt = ex.rd_run_potion_count();
  out.potionBeltHtml = document.getElementById("relicChips").innerHTML;
  await walkIntoFight();
  out.potionFight = !document.getElementById("handPanel").hidden;
  out.potionHasUse = Boolean(document.querySelector("[data-use-potion]"));
  const useButton = document.querySelector("[data-use-potion]");
  if (useButton) {
    // Call the handler **directly** so a throw is visible here instead of vanishing into the
    // event dispatcher (that is exactly how the regression above stayed invisible).
    try {
      useButton.onclick();
      out.potionThrew = null;
    } catch (error) {
      out.potionThrew = String(error);
    }
    await sleep(0);
  }
  out.potionAfter = ex.rd_run_potion_count();
  out.potionBeltAfter = document.getElementById("relicChips").innerHTML;
  return out;
})()`);

// ---- 4. the assertions ("key text must appear") -----------------------------------------------
const problems = [];
const want = (condition, why) => {
  if (!condition) problems.push(why);
};

want(report.blessings.length >= 2, `expected two blessings, got ${JSON.stringify(report.blessings)}`);
want(
  report.blessings.every((label) => !/^[a-z_]+$/.test(label)),
  `a blessing shows its raw id: ${JSON.stringify(report.blessings)}`
);
want(report.afterBlessing.pending === 0, `the blessing did not settle (pending ${report.afterBlessing.pending})`);
want(
  report.refusal.includes("走不过去"),
  `an unreachable node said ${JSON.stringify(report.refusal)}`
);
want(report.fight.inFight, "the fight did not start");
want(report.card?.open === true, "Shift+click did not open the card detail");
want((report.card?.body || "").length > 3, "the card detail has no text");
want(
  report.log.some((line) => line.includes("打出")),
  `the log does not name the card played: ${JSON.stringify(report.log)}`
);
want(
  /^幕 [0-9]/.test(report.topBar),
  `the top bar does not name the act: ${JSON.stringify(report.topBar)}`
);
want(
  report.energyAfter === 0 ? report.unaffordable > 0 : true,
  "with no energy left, no card is marked unaffordable"
);
// §150: the potion button must *do* something -- and a handler that throws counts as "did nothing".
want(report.potionInBelt === 1, `the reward did not hand over a potion (belt ${report.potionInBelt})`);
want(report.potionFight === true, "could not reach a second fight to use the potion in");
want(
  report.potionHasUse === true,
  "a potion in the belt offers no 用 button while in a fight"
);
want(report.potionThrew === null, `the potion button threw: ${report.potionThrew}`);
want(
  report.potionAfter === 0,
  `the potion was not consumed (still ${report.potionAfter} in the belt)`
);
want(
  !report.potionBeltAfter.includes("chip potion"),
  `the belt still shows the potion after using it: ${report.potionBeltAfter}`
);

socket.close();
chrome.kill();
server.close();
await rm(profile, { recursive: true, force: true }).catch(() => {});

if (problems.length) {
  for (const problem of problems) console.error("  - " + problem);
  fail(`${problems.length} assertion(s) failed`);
}
console.log("  blessings         " + report.blessings.join(" / "));
console.log("  refusal           " + report.refusal);
console.log("  card detail       " + report.card.title + " · " + report.card.body);
console.log("  log               " + report.log[report.log.length - 1]);
console.log("  top bar           " + report.topBar);
console.log("  energy/unafford.  " + report.energyAfter + " / " + report.unaffordable);
console.log("  potion            belt " + report.potionInBelt + " -> " + report.potionAfter +
  (report.potionThrew ? " · THREW " + report.potionThrew : ""));
console.log("BROWSER_TEST PASS");
