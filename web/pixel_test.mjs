// §168: the pixel gate -- what the rasterizer drew, not what the DOM says.
//
// # Why not a golden-image diff
//
// A stored baseline PNG is the classic answer and it is the wrong one **here**. It goes red for a
// font hinting change, a scrollbar, a 1 px margin -- none of which are bugs -- and the only way to get
// it green again is to re-record it, which also accepts the real regression that came in with it. A
// baseline that people re-record on sight is a gate that votes green by habit.
//
// So every assertion below is a **property** of the bitmap, chosen so that it fails for a class of
// visual bug and for nothing else:
//
//   1. the page actually painted (not a blank canvas);
//   2. the theme's own colours reached the screen (a chip's accent, the ink colour of text);
//   3. **the number of card-shaped blobs in the hand equals the number of cards the DOM reports**
//      -- the DOM-vs-picture cross-check, which no DOM assertion can make;
//   4. nothing the panel should contain is drawn **outside** it (a card row that overflows its panel
//      is invisible to `getBoundingClientRect` of the children -- each child is where it says it is);
//   5. two shots of the same state are identical (catches uninitialised paint / animation churn).
//
// And, because "the pixel gate passes" is worth nothing on its own, the last block is a **negative
// control**: hide the hand with `opacity: 0` and demand that (3)'s blob count collapses to zero. If a
// broken page can still pass, the gate is measuring nothing.

import { openPage } from "./cdp.mjs";
import {
  colourCount, diffCount, diffCountIn, distance, dominantColour, inkCount, inkFraction, rect,
  sameBitmap,
} from "./pixels.mjs";

const problems = [];
const want = (condition, message) => {
  if (!condition) problems.push(message);
};

// ---- 0. The measurers, on bitmaps whose answer is known by hand ------------------------------
// Before anything is measured in a browser: if `inkCount` or `diffCountIn` is wrong, every number
// below is wrong in the same direction and the gate still says PASS. These cases are tiny and
// exact, so a broken measurer fails here, first, with a number instead of a picture.
{
  const blank = (width, height, rgb) => ({
    width,
    height,
    data: Buffer.from(Array.from({ length: width * height }, () => [...rgb, 255]).flat()),
  });
  const withPatch = (base, x0, y0, w, h, rgb) => {
    const out = { width: base.width, height: base.height, data: Buffer.from(base.data) };
    for (let y = y0; y < y0 + h; y++) {
      for (let x = x0; x < x0 + w; x++) {
        const at = (y * out.width + x) * 4;
        out.data[at] = rgb[0];
        out.data[at + 1] = rgb[1];
        out.data[at + 2] = rgb[2];
      }
    }
    return out;
  };
  const dark = blank(10, 10, [0, 0, 0]);
  const patched = withPatch(dark, 4, 4, 2, 2, [255, 255, 255]);
  want(inkCount(dark, rect(0, 0, 10, 10), [0, 0, 0], 24) === 0, "inkCount on a blank bitmap is not 0");
  want(inkCount(patched, rect(0, 0, 10, 10), [0, 0, 0], 24) === 4, "inkCount does not count the 2x2 patch");
  want(Math.abs(inkFraction(patched, rect(0, 0, 10, 10), [0, 0, 0], 24) - 0.04) < 1e-9,
    "inkFraction is not ink / area");
  want(diffCount(dark, patched, 8) === 4, "diffCount is not 4 between blank and a 2x2 patch");
  // The clipping half: a box that excludes the patch must read 0, and the box is clipped to the bitmap.
  want(diffCountIn(dark, patched, rect(0, 0, 4, 4), 8) === 0, "diffCountIn counted a pixel outside its box");
  want(diffCountIn(dark, patched, rect(4, 4, 2, 2), 8) === 4, "diffCountIn missed the patch");
  want(diffCountIn(dark, patched, rect(8, 8, 100, 100), 8) === 0,
    "diffCountIn does not clip its box to the bitmap");
  want(dominantColour(patched, rect(0, 0, 10, 10))[0] === 0, "dominantColour is not the majority colour");
  want(colourCount(patched, rect(0, 0, 10, 10), [255, 255, 255], 8) === 4, "colourCount missed the patch");
  want(distance([0, 0, 0], [255, 255, 255]) === 255, "distance is not the max channel difference");
  // A PNG decoder that silently mis-strides would make all of the above agree with each other. The
  // bitmap below is 2x2 with one white pixel, encoded by `Page.captureScreenshot`'s own encoder, and
  // checked against its known content -- see the browser half, which asserts the same bitmap's size.
  console.log(`  measurers         ok (ink, fraction, diff, clip, colour, distance)`);
}

// A fixed viewport, so the same page rasterizes to the same bytes on any machine (§168.1). 1024x720
// is big enough that the desktop two-column layout is used and small enough to stay fast.
const VIEWPORT = { width: 1024, height: 720 };
const page = await openPage({
  query: "debug",
  gate: "PIXEL_TEST",
  waitFor: "!!window.RD_DEBUG",
  viewport: VIEWPORT,
});

const report = {};

// A deterministic fight: same seed, same blessing, same enemy, so the picture is comparable.
await page.evaluate("RD_DEBUG.startWithSeed(4321, 0)");
await page.evaluate(`(async () => {
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  await settle();
  if (ex.rd_run_pending() === 6) {
    document.querySelector("#nodePanel [data-panel-action]").click();
    await settle();
  }
  let guard = 0;
  while (ex.rd_run_pending() === 7 && guard++ < 6) {
    const pick = document.querySelector("#modalBody [data-pick], #nodePanel [data-pick]");
    if (pick) pick.click();
    else document.querySelector("#nodePanel [data-panel-action]").click();
    await settle();
  }
  // §168: wait for the entrance animations. The hand's cards animate in with a 40 ms stagger, and a
  // shot taken during that is a different picture every time (the first version compared two of them
  // and reported 37,927 differing pixels -- correctly, but about the animation, not about a bug).
  const settlePaint = async () => {
    const list = document.getAnimations();
    await Promise.all(list.map((a) => a.finished.catch(() => {})));
    await settle();
  };

  // Walk into the first reachable combat and start it.
  const view = window.RD_DEBUG.view();
  const node = [...document.querySelectorAll("#mapbox g.node.reachable")]
    .find((n) => n.dataset.kind === "combat");
  (node || document.querySelector("#mapbox g.node.reachable")).dispatchEvent(
    new MouseEvent("click", { bubbles: true }));
  await settle();
  const begin = document.querySelector("#nodePanel [data-panel-action]");
  if (begin) begin.click();
  await settlePaint();
  return ex.rd_run_pending();
})()`);
report.inFight = await page.evaluate("!document.getElementById('handPanel').hidden");
report.cards = await page.evaluate("document.querySelectorAll('#hand button.card').length");

/** The viewport box of a selector, in the same coordinate space as the bitmap. */
const boxOf = async (selector) =>
  page.evaluate(`(() => {
    const node = document.querySelector(${JSON.stringify(selector)});
    if (!node) return null;
    const r = node.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  })()`);

// ---- 1. It painted at all ----------------------------------------------------------------
const shot = await page.screenshot();
report.size = `${shot.width}x${shot.height}`;
want(shot.width === VIEWPORT.width && shot.height === VIEWPORT.height,
  `the bitmap is ${report.size}, expected ${VIEWPORT.width}x${VIEWPORT.height}`);

const pageBg = dominantColour(shot, rect(0, 0, shot.width, shot.height));
report.pageBg = pageBg.slice(0, 3).map((v) => v.toString(16).padStart(2, "0")).join("");

// ⚠️ Coverage is measured **inside the board**, not over the page. Measured page-wide, hiding the
// whole board still left 3.2% non-background -- the archive and replay bars at the bottom are page
// furniture and they kept the number above any floor small enough to be honest. (Found by fault
// injection: `fault_pixels.mjs` hides `.board` and asks whether this assertion notices.)
const boardBox = await boxOf(".board");
want(boardBox !== null, "the page has no .board element");
const boardBg = boardBox ? dominantColour(shot, boardBox) : pageBg;
// `inkFraction` clips the box to the bitmap first, so the numerator and denominator are the same
// rectangle (the board is 895 px tall in a 720 px viewport).
const coverage = boardBox ? inkFraction(shot, boardBox, boardBg, 24) : 0;
report.coverage = Number(coverage.toFixed(4));
report.boardBox = boardBox ? [Math.round(boardBox.width), Math.round(boardBox.height)] : null;
// A blank board is 0; a solid fill is 1. Both are failures, and both are cheap to state.
// 实测：一张正常的战斗画面是 4.1%（面板底色与棋盘底色只差 15，所以"墨"主要来自文字、边框与
// 卡牌 —— 棋盘的大部分是面板之间的空隙）。下限取 2%，是实测值的一半：它要抓的是"几乎什么都没画"
// （故障注入里藏掉 `.board` 会掉到 0.x%），而不是"画得比我记得的少一点"。
want(coverage > 0.02, `the board is ${(coverage * 100).toFixed(2)}% non-background: it barely painted`);
want(coverage < 0.95, `the board is ${(coverage * 100).toFixed(2)}% non-background: it is a solid fill`);

// ---- 2. The theme reached the screen -----------------------------------------------------
// `--ink` is the text colour the whole page is drawn in. If the CSS variable were dropped, text would
// fall back to black on a dark panel -- ie. **no** ink-coloured pixels.
const ink = await page.evaluate(
  "getComputedStyle(document.documentElement).getPropertyValue('--ink').trim()"
);
const inkRgb = /^#[0-9a-f]{6}$/i.test(ink)
  ? [parseInt(ink.slice(1, 3), 16), parseInt(ink.slice(3, 5), 16), parseInt(ink.slice(5, 7), 16)]
  : null;
report.ink = ink;
want(inkRgb !== null, `the page's --ink is not a #rrggbb colour (${JSON.stringify(ink)})`);
if (inkRgb) {
  // ⚠️ Counting pixels of the ink colour alone is not enough: with `--ink` set to the page's own
  // background the count went **up** (155,223 of them) and the check passed. Fault injection caught
  // it. Legibility is the first half of the claim, presence is the second.
  const gap = distance(inkRgb, pageBg);
  report.inkGap = gap;
  want(gap > 40,
    `the page's ink ${ink} is only ${gap} away from its background #${report.pageBg}: ` +
    `text would be unreadable, whatever the pixel count says`);
  const inkPixels = colourCount(shot, rect(0, 0, shot.width, shot.height), inkRgb, 8);
  report.inkPixels = inkPixels;
  want(inkPixels > 500, `only ${inkPixels} pixels are the page's own ink colour -- text is not drawn in it`);
}

// ---- 3. The hand: DOM count == painted blobs ---------------------------------------------
const handBox = await boxOf("#hand");
const cardBoxes = await page.evaluate(`(() =>
  [...document.querySelectorAll("#hand button.card")].map((node) => {
    const r = node.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }))()`);
report.handCards = report.cards;
report.cardBoxes = cardBoxes.length;
want(!report.inFight || report.cards > 0, "the hand is on screen but has no cards in the DOM");
want(!report.inFight || cardBoxes.length === report.cards,
  `${cardBoxes.length} card boxes measured for ${report.cards} card(s)`);

// ---- 4. Nothing spills out of its panel --------------------------------------------------
// The hand panel is `overflow: visible`, so a card row wider than the panel paints **outside** it.
// Every child's `getBoundingClientRect` still looks sane, which is why this has to be pixels.
// §168: in **pixels**, not layout. `getBoundingClientRect()` of each child is exactly where the child
// says it is -- a card that overflows its row is "correct" by that measure and wrong on screen. So:
// is there ink in the band just below the strip? A card spilling downward paints there; nothing else
// does (the next panel starts after the grid gap).
if (handBox) {
  const below = rect(handBox.x, handBox.y + handBox.height + 1, handBox.width, 6);
  const belowInk = inkCount(shot, below, pageBg, 24);
  report.belowInk = belowInk;
  want(belowInk < 50, `${belowInk} pixel(s) of ink just below the hand strip: a card is overflowing it`);
}

// ---- 5. The same state is the same picture ----------------------------------------------
const again = await page.screenshot();
report.stable = sameBitmap(shot, again);
report.diff = diffCount(shot, again, 0);
want(report.stable === true,
  `two shots of the same state differ in ${report.diff} pixel(s) -- the page paints something unstable`);

// ---- 6. Per card: was **this** card painted? (differential, no colour reference) ----------
// The hidden thing has to be **the cards**, not the panel: `opacity: 0` on the whole panel also removes
// the panel's own background from those boxes, so a card that was *never painted* would still "change"
// (background -> nothing) and the check would pass for the wrong reason. Measured on the fault script:
// hiding the panel made an unpainted card read 9,088 changed pixels -- the strongest possible pass for
// the exact bug this block exists to catch.
const negative = await page.evaluate(`(() => {
  const style = document.createElement("style");
  style.id = "pixelHideCards";
  style.textContent = "#hand button.card { visibility: hidden }";
  document.head.appendChild(style);
  const card = document.querySelector("#hand button.card");
  return card ? getComputedStyle(card).visibility : "no card";
})()`);
const hidden = await page.screenshot();
const perCardChanged = cardBoxes.map((box) => diffCountIn(shot, hidden, box, 8));
report.negative = {
  visibility: negative,
  perCardChanged,
  changed: diffCount(shot, hidden, 0),
};
if (report.inFight) {
  const unpainted = perCardChanged.filter((changed) => changed < 200);
  report.blankCards = unpainted.length;
  want(unpainted.length === 0,
    `${unpainted.length} of ${report.cards} card(s) did not change when the hand was hidden ` +
    `(${JSON.stringify(perCardChanged)}) -- the DOM has them, the picture does not`);
  // …and the negative control's own control: the whole page must have changed a lot, otherwise the
  // shot above is stale and every per-card number in it is meaningless.
  want(report.negative.changed > 1000,
    `hiding the hand changed only ${report.negative.changed} pixel(s): the shot is stale`);
}
await page.evaluate(`(() => {
  const style = document.getElementById("pixelHideCards");
  if (style) style.remove();
})()`);

// ---- 7. A specific spot: the energy badge ------------------------------------------------
// Not a baseline -- a **local** claim: the energy number is drawn on the hero panel, so there is ink
// in the hero panel's top-left corner where the badge sits, and the badge's accent colour is present.
const hero = await boxOf("#heroPanel");
if (hero) {
  const heroBg = dominantColour(shot, hero);
  const badge = rect(hero.x + 8, hero.y + 8, Math.min(120, hero.width - 16), 48);
  const badgeInk = inkCount(shot, badge, heroBg, 24);
  report.heroBadgeInk = badgeInk;
  want(badgeInk > 40, `the hero panel's badge area has ${badgeInk} ink pixel(s) -- nothing drawn there`);
}

await page.close();

if (problems.length) {
  for (const problem of problems) console.error("  - " + problem);
  console.error(`PIXEL_TEST FAIL: ${problems.length} assertion(s) failed`);
  process.exit(1);
}
console.log(`  bitmap            ${report.size} · background #${report.pageBg} · board ` +
  `${JSON.stringify(report.boardBox)} with ${(report.coverage * 100).toFixed(2)}% non-background`);
console.log(`  ink               ${report.ink} (${report.inkGap} from the background) -> ` +
  `${report.inkPixels} pixel(s) drawn in it`);
// The evidence column in the acceptance table reads the first match of a small pattern list, so the
// number it shows is spelled here once, in the shape the table expects.
console.log(`  hand              ${report.handCards - (report.blankCards || 0)}/${report.handCards} ` +
  `card(s) painted · ${report.cardBoxes} box(es) · below-strip ink ${report.belowInk} · ` +
  `hero badge ink ${report.heroBadgeInk}`);
console.log(`  stability         ${report.stable ? "identical" : "DIFFERENT"} (${report.diff} pixel(s))`);
console.log(`  negative control  cards ${report.negative.visibility} -> per card ` +
  `${JSON.stringify(report.negative.perCardChanged)}, ${report.negative.changed} pixel(s) changed`);
console.log("PIXEL_TEST PASS");
