// 闸门 52 `ui-cardface`：**卡面真的有东西，而且贴在牌上**。
//
// 用户报的原始现象："卡面是空的，没有显示之前准备的二维矢量素材"。
//
// 查下来是**两个**问题叠在一起：
//
// 1. **`run.html` 根本没加载 `styles.css`** ⇒ 战斗屏的 DOM 覆盖层（卡面文字/详情/提示条）
//    全是未样式的普通 div，`.text-layer` 的 `position` 是 `static`，卡面文字飘在页面最下面
//    （实测 y=1234，而牌在 y=591）—— 所以"卡面是空的"其实是"卡面文字在屏幕外"。
// 2. 就算样式在，徽章也**没接**：手牌与卡牌详情从来没画过 `Badge`；而且 `ViewCard.id` 是
//    合成 id（`hand-<slot>-<defSlot>`），拿它查素材表会走**降级**。
//
// 之前的 51 道闸门都没抓到，因为它们断言的是**文本内容**（`textContent` 里有"防御"），
// 不是**几何位置**与**样式是否生效**。所以这一道补三件：
//
//   * `.text-layer` 必须真的被样式化（`position !== "static"`）；
//   * 每张手牌的 DOM 中心必须**落在牌心上**（±10px）；
//   * 每张手牌与详情卡必须有徽章，字母与 `badgeLook("cards", defId)` 一致，
//     且素材注册表**没有降级**（拿合成 id 查表会让 `assetsUnknown()` 非空）。

import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { openPage } from "../web/cdp.mjs";

const GATE = "UI_CARDFACE";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let failures = 0;
const check = (ok, label, detail = "") => {
  console.log(`${ok ? "ok  " : "FAIL"} ${label}${detail ? ` -- ${detail}` : ""}`);
  if (!ok) failures += 1;
  return ok;
};
const summary = { cards: 0, maxOffset: 0, letters: [] };

try {
  execFileSync(process.execPath, [join("web-next", "scripts", "sync-wasm.mjs")], { stdio: "pipe" });
} catch {
  console.error(`${GATE} FAIL: 同步 wasm 失败（先跑内核构建）`);
  process.exit(1);
}

const page = await openPage({
  page: "web-next/dist/run.html",
  query: "motion=off",
  gate: GATE,
  viewport: { width: 1280, height: 800 },
  waitFor: "Boolean(window.__run && window.__run.ready)",
});
const ev = (expression) => page.evaluate(expression);

// ── 走到战斗 ───────────────────────────────────────────────────────────────
await ev("window.__run.start(1, 0)");
const blessings = await ev("window.__run.blessings()");
const simple = blessings.find((blessing) => !/card/.test(blessing.id));
await ev(`window.__run.choose(${simple.slot})`);
if ((await ev("window.__run.scene()")).base === "SC-01b") {
  await ev("window.__run.pickBlessingCard(0)");
}
const map = await ev("window.__run.map()");
const node = map.nodes.filter((entry) => entry.reachable).find((entry) => entry.kind === 1);
await ev(`window.__run.enter(${node.index})`);
await ev("window.__run.fightBegin()");
await sleep(600);

// ── 1. 样式真的加载了（这一条就是"卡面是空的"的根因）──────────────────────
const layerStyle = await ev(`(() => {
  const el = document.querySelector(".text-layer");
  if (!el) return null;
  const style = getComputedStyle(el);
  return { position: style.position, pointerEvents: style.pointerEvents };
})()`);
check(layerStyle !== null, "手牌文字层存在（`.text-layer`）");
check(
  layerStyle !== null && layerStyle.position !== "static",
  "文字层被**样式化**了（`position !== static`）—— `run.html` 必须加载 styles.css",
  JSON.stringify(layerStyle)
);
check(
  layerStyle !== null && layerStyle.pointerEvents === "none",
  "文字层不吃指针事件（拖牌要能穿过去）",
  String(layerStyle?.pointerEvents)
);

// ── 2. 每张手牌的 DOM 中心落在牌心上 ──────────────────────────────────────
const geometry = await ev(`(() => {
  const layout = window.__p1.layout();
  const rows = [];
  for (const node of Array.from(document.querySelectorAll("[data-card]"))) {
    const slot = Number(node.dataset.card);
    const card = layout.cards.find((entry) => entry.slot === slot);
    if (!card) continue;
    const rect = node.getBoundingClientRect();
    rows.push({
      slot,
      domX: Math.round(rect.x + rect.width / 2),
      domY: Math.round(rect.y + rect.height / 2),
      cardX: Math.round(card.hitX),
      cardY: Math.round(card.hitY),
    });
  }
  return rows;
})()`);
summary.cards = geometry.length;
check(summary.cards > 0, "手牌在 DOM 里（有 `[data-card]`）", String(summary.cards));
const offsets = geometry.map((row) => Math.hypot(row.domX - row.cardX, row.domY - row.cardY));
summary.maxOffset = Math.round(Math.max(...offsets, 0));
check(
  offsets.every((offset) => offset <= 10),
  "每张牌的卡面文字**落在牌心上**（±10px）",
  `最大偏移 ${summary.maxOffset}px`
);

// ── 3. 每张手牌都有徽章，字母与内容 id 对得上 ─────────────────────────────
const faces = await ev(`(() => {
  const layout = window.__p1.layout();
  return Array.from(document.querySelectorAll("[data-card]")).map((node) => {
    const slot = Number(node.dataset.card);
    const card = layout.cards.find((entry) => entry.slot === slot);
    const badge = node.querySelector("[data-card-art] [data-asset-badge]");
    return {
      slot,
      hasArt: Boolean(node.querySelector("[data-card-art]")),
      letters: badge ? badge.dataset.assetLetters : null,
      assetId: badge ? badge.dataset.assetId : null,
      kind: badge ? badge.dataset.assetBadge : null,
      cardX: card ? Math.round(card.hitX) : null,
    };
  });
})()`);
const missingArt = faces.filter((face) => !face.hasArt);
check(missingArt.length === 0, "每张手牌都有卡面素材块（`[data-card-art]`）", JSON.stringify(missingArt.map((f) => f.slot)));
const badLetters = faces.filter((face) => !/^[A-Z]{2}$/.test(String(face.letters ?? "")));
check(badLetters.length === 0, "每张手牌上的字母是两位大写", JSON.stringify(badLetters.map((f) => f.letters)));
summary.letters = faces.map((face) => face.letters);
check(
  faces.every((face) => face.kind === "cards"),
  "徽章的表是 `cards`（不是遗物/药水）",
  JSON.stringify(faces.map((face) => face.kind))
);

// 字母必须来自**内容 id**（`strike` → ST），不是合成 id（`hand-0-1` → HA）。
// 合成 id 还会让注册表走降级 —— 下面那条 `assetsUnknown()` 直接抓它。
const expected = await ev(`window.__p1.handFaces()`);
check(Array.isArray(expected) && expected.length === faces.length, "探针给了每张牌的期望字母", JSON.stringify(expected?.slice(0, 3)));
if (Array.isArray(expected)) {
  const mismatch = expected.filter((row) => {
    const face = faces.find((entry) => entry.slot === row.slot);
    return !face || face.letters !== row.letters || face.assetId !== row.defId;
  });
  check(
    mismatch.length === 0,
    "界面上的字母与 id 都等于**内容 id** 查出来的那一份",
    JSON.stringify(mismatch.slice(0, 3))
  );
}

// ── 4. 素材注册表没有降级（拿合成 id 查表会让它非空）──────────────────────
const unknown = await ev("window.__run.assetsUnknown()");
check(
  Array.isArray(unknown) && unknown.length === 0,
  "素材注册表没有降级（每个 id 都在清单里）",
  JSON.stringify(unknown)
);

// ── 5. 卡牌详情也有立绘（56px）────────────────────────────────────────────
await ev("window.__p1.openDetail(0)");
await sleep(250);
const detail = await ev(`(() => {
  const badge = document.querySelector("[data-detail-art] [data-asset-badge]");
  if (!badge) return null;
  return {
    letters: badge.dataset.assetLetters,
    assetId: badge.dataset.assetId,
    width: Math.round(badge.getBoundingClientRect().width),
  };
})()`);
check(detail !== null, "卡牌详情有立绘块（`[data-detail-art]`）");
check(detail !== null && /^[A-Z]{2}$/.test(String(detail.letters)), "详情立绘的字母是两位大写", String(detail?.letters));
check(detail !== null && detail.width >= 48, "详情立绘够大（>= 48px）", `${detail?.width}px`);
const detailMatches = detail !== null && faces.some((face) => face.assetId === detail.assetId);
check(detailMatches, "详情立绘与那张手牌是同一个 id", JSON.stringify({ detail: detail?.assetId, hand: faces[0]?.assetId }));
await ev("window.__p1.openDetail(0)");

await page.close();
console.log("");
if (failures > 0) {
  console.error(`${GATE} FAIL: ${failures} 条`);
  process.exit(1);
}
console.log(
  `UI_CARDFACE PASS cards=${summary.cards} offset=${summary.maxOffset}px letters=${summary.letters.join(",")}`
);
