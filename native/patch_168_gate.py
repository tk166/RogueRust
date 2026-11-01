"""§168 (revision): per-card ink instead of blob counting; wait for animations first.

The first version failed for two informative reasons, both now baked into the fixture:

  1. **the hand has entrance animations** (`animation-delay: order * 40ms`), so two shots of "the same
     state" differed by 37,927 pixels. The state was the same; the paint was mid-flight. Every
     measurement is now taken after `document.getAnimations()` finished -- the page is asked, not slept on;
  2. **blob counting is the wrong shape for this layout** (see `inkPerBox` in pixels.mjs): the cards do
     not separate into blobs, so "5 blobs for 5 cards" was a threshold fitted to one layout. The claim
     is now per card: *this* card's rectangle contains ink.
"""
import io

PATH = "web/pixel_test.mjs"


def main():
    text = io.open(PATH, encoding="utf-8").read()

    # (a) the fixture must wait for the paint to settle, not for a clock.
    old = """  // Walk into the first reachable combat and start it."""
    new = """  // §168: wait for the entrance animations. The hand's cards animate in with a 40 ms stagger, and a
  // shot taken during that is a different picture every time (the first version compared two of them
  // and reported 37,927 differing pixels -- correctly, but about the animation, not about a bug).
  const settlePaint = async () => {
    const list = document.getAnimations();
    await Promise.all(list.map((a) => a.finished.catch(() => {})));
    await settle();
  };

  // Walk into the first reachable combat and start it."""
    assert text.count(old) == 1
    text = text.replace(old, new)

    old = """  if (begin) begin.click();
  await settle();
  return ex.rd_run_pending();
})()`);"""
    new = """  if (begin) begin.click();
  await settlePaint();
  return ex.rd_run_pending();
})()`);"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    # (b) the hand claim: per-card ink.
    old = """const handBox = await boxOf("#hand");
const handBg = handBox ? dominantColour(shot, handBox) : null;
const blobs = handBox ? columnBlobs(shot, handBox, handBg, { minWidth: 10 }) : [];
report.handBlobs = blobs.length;
report.handCards = report.cards;
if (report.inFight) {
  want(report.cards > 0, "the hand is on screen but has no cards in the DOM");
  // Card borders/gaps make this exact (each card is one blob at its own x-range) -- and if the hand
  // ever renders every card into one solid strip, this drops to 1 and says so.
  want(report.handBlobs === report.cards,
    `the hand painted ${report.handBlobs} card blob(s) for ${report.cards} card(s) in the DOM`);
} else {
  console.log("  note: the fixture did not reach a fight; the hand half did not run");
}"""
    new = """const handBox = await boxOf("#hand");
const handBg = handBox ? dominantColour(shot, handBox) : null;
const cardBoxes = await page.evaluate(`(() =>
  [...document.querySelectorAll("#hand button.card")].map((node) => {
    const r = node.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }))()`);
const cardInk = handBg ? inkPerBox(shot, cardBoxes, handBg, 24) : [];
report.handCards = report.cards;
report.cardInk = cardInk;
if (report.inFight) {
  want(report.cards > 0, "the hand is on screen but has no cards in the DOM");
  want(cardBoxes.length === report.cards,
    `${cardBoxes.length} card boxes measured for ${report.cards} card(s)`);
  // A painted card is mostly text and a border, so a healthy one has hundreds of ink pixels. The floor
  // is a tenth of the smallest healthy measurement so it fails for "not painted", not for "a shorter
  // card title".
  const blank = cardInk.filter((ink) => ink < 40);
  report.blankCards = blank.length;
  want(blank.length === 0,
    `${blank.length} of ${report.cards} card(s) have almost no ink in their own rectangle ` +
    `(${JSON.stringify(cardInk)}) -- the DOM has them, the picture does not`);
} else {
  console.log("  note: the fixture did not reach a fight; the hand half did not run");
}"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    # (c) overflow, measured in pixels: ink below the hand strip.
    old = """const handPanel = await boxOf("#handPanel");
if (handPanel && handBox) {
  const spill = await page.evaluate(`(() => {
    const panel = document.getElementById("handPanel").getBoundingClientRect();
    let worst = 0;
    for (const node of document.querySelectorAll("#hand button.card")) {
      const r = node.getBoundingClientRect();
      worst = Math.max(worst, panel.left - r.left, r.right - panel.right);
    }
    return worst;
  })()`);
  report.spill = Math.round(spill);
  // A little slack for the focus ring / border radius; a real overflow is tens of pixels.
  want(spill <= 4, `a hand card is drawn ${Math.round(spill)} px outside #handPanel`);
}"""
    new = """// §168: in **pixels**, not layout. `getBoundingClientRect()` of each child is exactly where the child
// says it is -- a card that overflows its row is "correct" by that measure and wrong on screen. So:
// is there ink in the band just below the strip? A card spilling downward paints there; nothing else
// does (the next panel starts after the grid gap).
if (handBox) {
  const below = rect(handBox.x, handBox.y + handBox.height + 1, handBox.width, 6);
  const belowInk = inkCount(shot, below, pageBg, 24);
  report.belowInk = belowInk;
  want(belowInk < 50, `${belowInk} pixel(s) of ink just below the hand strip: a card is overflowing it`);
}"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    # (d) the negative control uses the same per-card measurement.
    old = """const hidden = await page.screenshot();
const hiddenBox = await boxOf("#hand");
const hiddenBlobs = hiddenBox ? columnBlobs(hidden, hiddenBox, handBg, { minWidth: 10 }) : [];
// `opacity: 0` also makes the element invisible to hit-testing, so the box can legitimately be
// zero-sized afterwards; what must not happen is "still N blobs".
report.negative = { opacity: negative, blobs: hiddenBlobs.length };
if (report.inFight) {
  want(hiddenBlobs.length === 0,
    `after hiding the hand, ${hiddenBlobs.length} card blob(s) were still painted -- ` +
    `the blob count is not measuring the picture`);
  want(diffCount(shot, hidden, 0) > 1000,
    `hiding the hand changed only ${diffCount(shot, hidden, 0)} pixel(s): the shot is stale`);
}"""
    new = """const hidden = await page.screenshot();
const hiddenCardBoxes = await page.evaluate(`(() =>
  [...document.querySelectorAll("#hand button.card")].map((node) => {
    const r = node.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }))()`);
const hiddenInk = handBg ? inkPerBox(hidden, hiddenCardBoxes, handBg, 24) : [];
const hiddenTotal = hiddenInk.reduce((sum, ink) => sum + ink, 0);
report.negative = { opacity: negative, ink: hiddenTotal, boxes: hiddenCardBoxes.length };
if (report.inFight) {
  // `opacity: 0` keeps the layout (so the boxes are still there) and paints nothing -- which is
  // exactly the shape of "the DOM says 5 cards, the screen shows none". If this does not collapse to
  // ~0, the measurement below is not looking at the picture.
  want(hiddenTotal === 0,
    `after hiding the hand it still has ${hiddenTotal} ink pixel(s): the per-card ink is not ` +
    `measuring the picture`);
  const changed = diffCount(shot, hidden, 0);
  report.negative.changed = changed;
  want(changed > 1000, `hiding the hand changed only ${changed} pixel(s): the shot is stale`);
}"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    # (e) imports + the log line
    old = """import {
  columnBlobs, colourCount, diffCount, dominantColour, inkBounds, inkCount, pixelAt, rect,
  sameBitmap,
} from "./pixels.mjs";"""
    new = """import {
  colourCount, diffCount, dominantColour, inkCount, inkPerBox, rect, sameBitmap,
} from "./pixels.mjs";"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    old = """console.log(`  hand              ${report.handBlobs} blob(s) for ${report.handCards} DOM card(s) · ` +
  `spill ${report.spill} px · hero badge ink ${report.heroBadgeInk}`);"""
    new = """console.log(`  hand              ${report.handCards} card(s) · ink ${JSON.stringify(report.cardInk)} · ` +
  `blank ${report.blankCards} · below-strip ink ${report.belowInk} · hero badge ink ${report.heroBadgeInk}`);"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    old = """console.log(`  negative control  opacity ${report.negative.opacity} -> ${report.negative.blobs} blob(s)`);"""
    new = """console.log(`  negative control  opacity ${report.negative.opacity} -> ${report.negative.ink} ink ` +
  `in ${report.negative.boxes} box(es), ${report.negative.changed} pixel(s) changed`);"""
    assert text.count(old) == 1
    text = text.replace(old, new)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("pixel gate: per-card ink, animations awaited, overflow measured in pixels")


if __name__ == "__main__":
    main()
