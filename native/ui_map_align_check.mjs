// 闸门 54 `ui-map-align`：**"看得见的错"**——地图连线与节点对不上、敌人死了还站在场上。
//
// 这两条都是玩家实机截图报出来的，而且都属于同一类：**模型是对的，画出来是错的**。
// 所以断言必须在**像素/DOM** 上做，模型断言（闸门 34 那种）永远不会红。
//
// ## ① 地图：连线与节点必须落在同一批坐标上
//
// 根因（已修）：节点靠 CSS `flex-direction: column-reverse` 把第 1 行翻到底部，而 SVG 连线
// 用 `y = (1 - row/lastRow)` —— **两层互为镜像**。玩家看到的是"高亮的线往**下**走，可达节点
// 却在上面"。现在节点绝对定位在 `map.layout` 的归一化坐标上，与 `<line>` 同一个公式。
//
// 判据（三条，缺一条这个 bug 就能复活）：
//   a. **每一条线的两个端点都落在它声明的那两个节点的中心**（±2.5px）；
//   b. **行号越大越靠上**（row 0 在底部）—— 这条是"往上爬"的语义；
//   c. **高亮的那条线是从当前节点出发、且指向更上面一行**（回合推进方向）。
//
// ## ② 战场：死掉的敌人必须从场上消失
//
// 根因（已修）：`snapshot.enemies` 里 `alive = 0` 的格子照画（压暗 0.35 当"尸体"），
// 而且下一回合还会给它发一个新意图。现在视图层过滤掉 `alive === false`。
//
// 判据：**真打一场直到有敌人死掉**（不能只断言"现在是 0 个" —— 那可能是这一场没有敌人），
// 然后断言 DOM 上的敌人标签数 == 内核里还活着的敌人数，且死掉的那个槽位**没有**标签。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_MAP_ALIGN";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { edges: 0, worstPx: 0, killed: 0, liveEdges: 0 };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/run.html",
  query: "",
  gate: GATE,
  viewport: { width: 1280, height: 900 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

/** 开一局并走到地图（`seed 1` 与其它闸门一致）。 */
async function toMap() {
  await ev(`window.__run.click("[data-start]")`);
  await sleep(150);
  const blessings = await ev("window.__run.blessings()");
  const simple = blessings.find((row) => row.needs === 0) ?? blessings[0];
  await ev(`window.__run.click("[data-blessing='${simple.slot}']")`);
  await sleep(250);
  // 祝福可能要求先挑一张牌（`SC-01b`，`pending 7`）：牌组选择器会自动弹出，点第一张。
  if ((await ev("window.__run.scene()")).base === "SC-01b") {
    const picked = await ev(`(() => {
      const node = document.querySelector("[data-deck-pick][data-deck-allowed='1']");
      if (!node) return null;
      node.click();
      return node.dataset.deckPick;
    })()`);
    check(picked !== null, "祝福要求的选牌有可点的牌", String(picked));
    await sleep(250);
  }
  return ev("window.__run.scene()");
}

/**
 * 读一次"地图的像素真相"：每个节点的中心、每条线的端点（都换成**视口**坐标）。
 *
 * ⚠️ 线的端点要从 `x1/y1` 属性换算：SVG 是 `viewBox="0 0 100 100"` +
 * `preserveAspectRatio="none"`，所以 `client = rect.left + x/100 * rect.width`。
 * 直接读 `getBBox()` 也行，但那是**局部**坐标，还得再补 SVG 自己的偏移 —— 一处算错就假绿。
 */
const readMapPixels = () =>
  ev(`(() => {
    const canvas = document.querySelector(".map-canvas");
    if (!canvas) return null;
    const nodes = {};
    for (const el of document.querySelectorAll("[data-node]")) {
      const r = el.getBoundingClientRect();
      nodes[el.dataset.node] = {
        x: r.left + r.width / 2,
        y: r.top + r.height / 2,
        row: Number(el.closest("[data-row]")?.dataset.row ?? -1),
        current: el.dataset.current === "1",
        reachable: el.dataset.reachable === "1",
      };
    }
    const svg = document.querySelector(".map-edges");
    const box = svg ? svg.getBoundingClientRect() : null;
    const lines = [];
    if (svg && box) {
      for (const line of svg.querySelectorAll("[data-edge]")) {
        const at = (x, y) => ({
          x: box.left + (Number(x) / 100) * box.width,
          y: box.top + (Number(y) / 100) * box.height,
        });
        lines.push({
          edge: line.dataset.edge,
          live: line.dataset.live === "1",
          from: at(line.getAttribute("x1"), line.getAttribute("y1")),
          to: at(line.getAttribute("x2"), line.getAttribute("y2")),
        });
      }
    }
    return { nodes, lines, canvasHeight: canvas.getBoundingClientRect().height };
  })()`);

/** 断言 a + b：每条线的端点落在节点中心、行号越大越靠上。 */
function assertMapPixels(pixels, label) {
  const nodes = pixels.nodes;
  let worst = 0;
  let bad = [];
  for (const line of pixels.lines) {
    const [fromIndex, toIndex] = line.edge.split("-");
    const from = nodes[fromIndex];
    const to = nodes[toIndex];
    if (!from || !to) {
      bad.push(`${line.edge}: 节点不存在`);
      continue;
    }
    const d1 = Math.hypot(line.from.x - from.x, line.from.y - from.y);
    const d2 = Math.hypot(line.to.x - to.x, line.to.y - to.y);
    worst = Math.max(worst, d1, d2);
    if (d1 > 2.5 || d2 > 2.5) {
      bad.push(`${line.edge}: 起点差 ${d1.toFixed(1)}px / 终点差 ${d2.toFixed(1)}px`);
    }
  }
  summary.edges = pixels.lines.length;
  summary.worstPx = Number(worst.toFixed(2));
  check(pixels.lines.length > 0, `${label}：地图上有连线可测`, `${pixels.lines.length} 条`);
  check(
    bad.length === 0,
    `${label}：每条线的两个端点都落在它声明的节点中心（±2.5px）`,
    bad.slice(0, 3).join(" / ") || `最差 ${worst.toFixed(2)}px`
  );

  // b. 行号越大越靠上：按 row 分组后，高行的**最低点**必须高于低行的**最高点**。
  const byRow = new Map();
  for (const node of Object.values(nodes)) {
    const list = byRow.get(node.row) ?? [];
    list.push(node.y);
    byRow.set(node.row, list);
  }
  const rows = Array.from(byRow.entries()).sort((a, b) => a[0] - b[0]);
  let orderBad = [];
  for (let index = 1; index < rows.length; index += 1) {
    const lower = rows[index - 1];
    const upper = rows[index];
    if (!(Math.max(...upper[1]) < Math.min(...lower[1]))) {
      orderBad.push(`row ${upper[0]} 没有比 row ${lower[0]} 更高`);
    }
  }
  check(
    orderBad.length === 0,
    `${label}：行号越大越靠上（第 1 行在底部）`,
    orderBad.slice(0, 2).join(" / ") || `${rows.length} 行`
  );
  return { nodes, rows };
}

// ── ① 开局的地图：连线与节点对齐 ────────────────────────────────────────────
const scene0 = await toMap();
check(scene0.base === "SC-02", "开局在地图屏", scene0.base);
await sleep(120);

const pixels0 = await readMapPixels();
check(pixels0 !== null, "地图 DOM 存在（.map-canvas / [data-node]）");
const map = await ev("window.__run.map()");
const { nodes, rows } = assertMapPixels(pixels0, "开局");
check(
  Math.abs(pixels0.canvasHeight - map.rows * 68) < 1.5,
  "画布高度 == 行数 × 行距（模型说的行距就是像素行距）",
  `${pixels0.canvasHeight.toFixed(1)} vs ${map.rows * 68}`
);
check(
  rows.length === map.rows,
  "屏幕上的行数 == 模型的 `rows`",
  `${rows.length} vs ${map.rows}`
);

// ── ② 走进第一格，把这一场打完（顺便证明"死掉的敌人会消失"）───────────────
const first = map.nodes.find((node) => node.reachable);
check(Boolean(first), "第 1 行有可达节点", String(first?.index));
await ev(`window.__run.click("[data-node='${first.index}']")`);
await sleep(200);
let scene = await ev("window.__run.scene()");

// 走到战斗：`SC-03`（战斗前）→ 开始战斗。
if (scene.base === "SC-03") {
  await ev(`window.__run.click("[data-fight-begin]")`);
  await sleep(400);
  scene = await ev("window.__run.scene()");
}

/** DOM 上的敌人标签槽位（`[data-enemy]` 来自 `TextOverlay`）。 */
const domEnemySlots = () =>
  ev(`Array.from(document.querySelectorAll("[data-enemy]")).map((el) => Number(el.dataset.enemy)).sort()`);

let deathChecked = false;
if (scene.base === "SC-03b") {
  check(true, "走进了一场战斗（这一格是战斗）");
  const before = await ev("window.__run.hand()");
  check(
    (await domEnemySlots()).length === before.enemies.filter((enemy) => enemy.hp > 0).length,
    "开战时：DOM 敌人标签数 == 活着的敌人数",
    JSON.stringify({ dom: await domEnemySlots(), kernel: before.enemies })
  );

  let steps = 0;
  for (; steps < 240; steps += 1) {
    const hand = await ev("window.__run.hand()");
    if (!hand || hand.result !== "ongoing") break;

    // 每一步之后检查"死了的有没有留在场上"。
    const dead = hand.enemies.filter((enemy) => enemy.hp <= 0);
    if (dead.length > 0 && !deathChecked) {
      await sleep(120); // 让 React 重渲染一帧
      const dom = await domEnemySlots();
      const alive = hand.enemies.filter((enemy) => enemy.hp > 0).map((enemy) => enemy.slot);
      const layoutSlots = await ev(
        "(() => { const l = window.__p1 && window.__p1.layout(); return l ? l.enemies.map((e) => e.slot).sort() : null; })()"
      );
      const corpses = dead.filter((enemy) => dom.includes(enemy.slot));
      check(
        corpses.length === 0,
        "死掉的敌人**不再有标签**（不是压暗的尸体）",
        `死者 ${JSON.stringify(dead.map((e) => e.slot))}，DOM ${JSON.stringify(dom)}`
      );
      check(
        JSON.stringify(dom) === JSON.stringify([...alive].sort()),
        "DOM 敌人标签 == 内核里还活着的敌人（不多不少）",
        `${JSON.stringify(dom)} vs ${JSON.stringify([...alive].sort())}`
      );
      if (layoutSlots) {
        check(
          JSON.stringify(layoutSlots) === JSON.stringify([...alive].sort()),
          "3D 命中布局里也没有尸体（拖牌不会命中它）",
          `${JSON.stringify(layoutSlots)} vs ${JSON.stringify([...alive].sort())}`
        );
      }
      deathChecked = true;
      summary.killed = dead.length;
    }

    const play = hand.actions.find((action) => action.kind === "play");
    const result = play
      ? await ev(`window.__run.play(${play.handSlot}, ${play.targetSlot})`)
      : await ev("window.__run.endTurn()");
    if (result?.accepted === false) {
      check(false, "战斗驱动没有卡住", JSON.stringify(result));
      break;
    }
  }
  check(deathChecked, "这一场里真的有敌人死了（否则上面那几条是空断言）", `steps=${steps}`);
} else {
  // 这一格不是战斗（`?` 房 / 商店 / 篝火）：跳过战场那一段，但要说清，不许静默通过。
  check(true, `这一格不是战斗（${scene.base}），战场部分跳过`);
}

// ── ③ 回到地图：高亮线从当前节点出发、指向更上面一行 ───────────────────────
scene = await ev("window.__run.scene()");
// 战斗屏在"有结果"之后仍然停在 `SC-03b`（等玩家点"领取奖励"），所以先点它。
if (scene.base === "SC-03b") {
  const continued = await ev(`(() => {
    const node = document.querySelector("[data-combat-continue]");
    if (!node) return false;
    node.click();
    return true;
  })()`);
  if (continued) await sleep(250);
  scene = await ev("window.__run.scene()");
}
if (scene.base === "SC-04") {
  await ev(`window.__run.click("[data-reward-skip]")`);
  await sleep(200);
} else if (scene.base !== "SC-02") {
  // 商店 / 篝火 / 宝箱 / 事件：一律"离开"回地图。
  const left = await ev(`(() => {
    const selectors = ["[data-shop-leave]", "[data-rest-leave]", "[data-chest-leave]"];
    for (const selector of selectors) {
      const node = document.querySelector(selector);
      if (node) { node.click(); return selector; }
    }
    return null;
  })()`);
  if (left) await sleep(200);
}
scene = await ev("window.__run.scene()");
if (scene.base === "SC-02") {
  await sleep(150);
  const pixels = await readMapPixels();
  assertMapPixels(pixels, "走了一格之后");
  const live = pixels.lines.filter((line) => line.live);
  summary.liveEdges = live.length;
  check(live.length > 0, "有高亮连线（从当前节点出发的那一步）", `${live.length} 条`);
  const currentIndex = (await ev("window.__run.run()")).node;
  let wrong = [];
  for (const line of live) {
    const [fromIndex, toIndex] = line.edge.split("-");
    if (Number(fromIndex) !== currentIndex) wrong.push(`${line.edge} 不是从当前节点 ${currentIndex} 出发`);
    const from = pixels.nodes[fromIndex];
    const to = pixels.nodes[toIndex];
    if (from && to && !(to.y < from.y)) wrong.push(`${line.edge} 没有指向更上面一行`);
    if (from && to && !(to.row === from.row + 1)) wrong.push(`${line.edge} 跨行不是 +1`);
  }
  check(
    wrong.length === 0,
    "高亮线从**当前节点**出发、且指向**上面一行**（往上爬）",
    wrong.slice(0, 2).join(" / ") || `current=${currentIndex}`
  );
} else {
  check(true, `没能回到地图（${scene.base}），高亮线部分跳过`);
}

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_MAP_ALIGN PASS edges=${summary.edges} worst=${summary.worstPx}px live=${summary.liveEdges} killed=${summary.killed}`
);
