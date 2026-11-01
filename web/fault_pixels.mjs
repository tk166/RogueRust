// §168: prove the pixel gate goes red. Each case injects a real visual bug and prints what the gate's
// own detectors say about it -- so the numbers in the doc are measured, not hoped for.
//
//   ink       the page's text colour set to the background colour  -> "ink pixels" must collapse
//   card      one card made invisible                              -> that card must read "unpainted"
//   overflow  the hand strip squeezed so cards spill               -> "below-strip ink" must appear
//   blank     the whole board hidden                                -> "coverage" must collapse
//
// Run: node web/fault_pixels.mjs
import { openPage } from "./cdp.mjs";
import { colourCount, diffCount, diffCountIn, distance, dominantColour, inkCount, inkFraction,
  rect } from "./pixels.mjs";

const fixture = `(async () => {
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  RD_DEBUG.startWithSeed(4321, 0);
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
  const node = [...document.querySelectorAll("#mapbox g.node.reachable")]
    .find((n) => n.dataset.kind === "combat");
  (node || document.querySelector("#mapbox g.node.reachable")).dispatchEvent(
    new MouseEvent("click", { bubbles: true }));
  await settle();
  const begin = document.querySelector("#nodePanel [data-panel-action]");
  if (begin) begin.click();
  await settle();
  await Promise.all(document.getAnimations().map((a) => a.finished.catch(() => {})));
  return ex.rd_run_pending();
})()`;

const cardBoxesOf = `(() =>
  [...document.querySelectorAll("#hand button.card")].map((node) => {
    const r = node.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }))()`;

const page = await openPage({
  query: "debug", gate: "PIXEL_FAULT", waitFor: "!!window.RD_DEBUG",
  viewport: { width: 1024, height: 720 },
});

const measure = async (label) => {
  const shot = await page.screenshot();
  const bg = dominantColour(shot, rect(0, 0, shot.width, shot.height));
  const boxes = await page.evaluate(cardBoxesOf);
  const hand = await page.evaluate(`(() => {
    const r = document.getElementById("hand").getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  })()`);
  const inkVar = await page.evaluate(
    "getComputedStyle(document.documentElement).getPropertyValue('--ink').trim()");
  const inkRgb = [parseInt(inkVar.slice(1, 3), 16), parseInt(inkVar.slice(3, 5), 16),
    parseInt(inkVar.slice(5, 7), 16)];
  const below = inkCount(shot, rect(hand.x, hand.y + hand.height + 1, hand.width, 6), bg, 24);
  // The board, exactly as the gate measures it.
  const board = await page.evaluate(`(() => {
    const r = document.querySelector(".board").getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  })()`);
  const boardBg = dominantColour(shot, board);
  return {
    label,
    coverage: Number(inkFraction(shot, board, boardBg, 24).toFixed(4)),
    inkGap: distance(inkRgb, bg),
    inkPixels: colourCount(shot, rect(0, 0, shot.width, shot.height), inkRgb, 8),
    belowInk: below,
    shot,
    boxes,
  };
};

// ---- clean -------------------------------------------------------------------------------
await page.evaluate(fixture);
const clean = await measure("clean");

// ---- fault: text colour == background ----------------------------------------------------
await page.evaluate(
  "document.documentElement.style.setProperty('--ink', getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#191d25')");
const inkFault = await measure("ink:#191d25");

// ---- fault: one card was never painted ---------------------------------------------------
// The shape the gate must catch is "the DOM has it, the screen never showed it" -- so the card is
// hidden **before** the reference shot, and the box that stays background in both shots is the tell.
await page.evaluate("document.documentElement.style.setProperty('--ink', '#d7dde8')");
// A **stylesheet** rule, not an inline style: the page rebuilds `#hand.innerHTML` on every render, and
// an inline style on a child is wiped by the next one (measured: the injected hide silently vanished
// and the detector read "all five cards changed"). A CSS rule is also the more realistic fault.
await page.evaluate(`(() => {
  const style = document.createElement("style");
  style.id = "faultHideCard2";
  style.textContent = "#hand button.card:nth-child(2) { visibility: hidden }";
  document.head.appendChild(style);
})()`);
const unpaintedShot = await page.screenshot();
console.log("  visibility applied:", await page.evaluate(
  "[...document.querySelectorAll('#hand button.card')].map(function (c) {" +
  " return getComputedStyle(c).visibility; }).join(',')"));
console.log("  clean vs unpainted per card:",
  JSON.stringify(clean.boxes.map((box) => diffCountIn(clean.shot, unpaintedShot, box, 8))));
// Hide the **cards** only (the panel keeps its background, so an unpainted card's box is unchanged).
await page.evaluate(`(() => {
  const style = document.createElement("style");
  style.id = "faultHideAllCards";
  style.textContent = "#hand button.card { visibility: hidden }";
  document.head.appendChild(style);
})()`);
const allHidden = await page.screenshot();
const cardFault = {
  label: "card2 never painted",
  perCard: clean.boxes.map((box) => diffCountIn(unpaintedShot, allHidden, box, 8)),
};
await page.evaluate(`(() => {
  for (const id of ["faultHideCard2", "faultHideAllCards"]) {
    const style = document.getElementById(id);
    if (style) style.remove();
  }
})()`);

// ---- fault: the hand spills out of its strip --------------------------------------------
await page.evaluate(`(() => {
  const strip = document.getElementById("hand");
  strip.style.height = "10px";
  strip.style.overflow = "visible";
})()`);
const overflow = await measure("hand:10px tall");
await page.evaluate(`(() => {
  const strip = document.getElementById("hand");
  strip.style.height = "";
  strip.style.overflow = "";
})()`);

// ---- fault: nothing painted at all -------------------------------------------------------
await page.evaluate("document.querySelector('.board').style.visibility = 'hidden'");
const blank = await measure("board:hidden");
const blankTotal = blank.coverage;

console.log("clean          board", clean.coverage, "ink gap", clean.inkGap,
  "ink", clean.inkPixels, "below", clean.belowInk, "cards", clean.boxes.length);
console.log("fault ink      gap", inkFault.inkGap, "  <- the legibility assertion needs gap > 40");
console.log("fault card     per card changed", JSON.stringify(cardFault.perCard),
  "  <- the card that was never painted must read < 200");
console.log("fault overflow below-strip ink", overflow.belowInk,
  "  <- the overflow assertion needs < 50");
console.log("fault blank    board", blankTotal, "  <- the coverage assertion needs > 0.02");
console.log("page diff (clean vs ink fault)", diffCount(clean.shot, inkFault.shot, 8));

await page.close();
