"""§168: the hand claim becomes differential -- no colour reference at all.

The previous shape was "count ink inside each card's box against the strip's dominant colour", and the
negative control killed it: after `opacity: 0` the strip shows what is *behind* it, whose colour is not
the reference, so 45,440 pixels still read as "ink". Any reference colour that is not the actual
backdrop is a guess, and a guess in a gate is a lie waiting for a different theme.

So the hand is measured by **difference**: take the shot with the cards visible, hide the hand, take it
again, and ask per card box "did this rectangle change?". A painted card must change; a card the DOM
has but the screen does not would leave its box untouched. No background colour is involved, so there
is nothing to fit to one theme.
"""
import io

PIXELS = "web/pixels.mjs"
GATE = "web/pixel_test.mjs"

OLD_PIXELS = '''/**
 * Ink inside each of several boxes (one per DOM element), returned in order.
 *
 * This replaced a "count the blobs across the strip" measurement, and the reason is worth keeping:
 * the hand's cards **do not** separate into blobs. Measured, each card is three or four runs of ink
 * (its cost badge, title, text, chips) with 1-3 px of background between them, while the gap
 * *between* two cards is the same order of magnitude. A blob counter therefore reported 18 "cards"
 * for 5 cards, and any threshold that made it say 5 was fitted to one layout.
 *
 * Asking "does **this** card's own rectangle contain ink" is the claim we actually want: the DOM
 * supplies coordinates, the bitmap answers whether anything was painted there.
 */
export function inkPerBox(bitmap, boxes, background, tolerance = 24) {
  return boxes.map((box) => inkCount(bitmap, box, background, tolerance));
}
'''

NEW_PIXELS = '''/**
 * Pixels that differ between two bitmaps **inside one box**.
 *
 * This is how "was it painted" is answered without naming a background colour: render the element,
 * hide it, render again, and ask whether its own rectangle changed. A painted element must change; an
 * element the DOM has but the screen does not leaves its box untouched.
 *
 * (A background-colour version of this was tried first and the negative control killed it: with the
 * element hidden, what shows through is *not* the colour you measured while it was visible.)
 */
export function diffCountIn(a, b, box, tolerance = 8) {
  if (a.width !== b.width || a.height !== b.height) return -1;
  const { x1, y1, x2, y2 } = clampRect(a, box);
  let different = 0;
  for (let y = y1; y < y2; y++) {
    for (let x = x1; x < x2; x++) {
      const at = (y * a.width + x) * 4;
      const worst = Math.max(
        Math.abs(a.data[at] - b.data[at]),
        Math.abs(a.data[at + 1] - b.data[at + 1]),
        Math.abs(a.data[at + 2] - b.data[at + 2])
      );
      if (worst > tolerance) different += 1;
    }
  }
  return different;
}
'''

OLD_HAND = '''const handBox = await boxOf("#hand");
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
}'''

NEW_HAND = '''const handBox = await boxOf("#hand");
const cardBoxes = await page.evaluate(`(() =>
  [...document.querySelectorAll("#hand button.card")].map((node) => {
    const r = node.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }))()`);
report.handCards = report.cards;
report.cardBoxes = cardBoxes.length;
want(!report.inFight || report.cards > 0, "the hand is on screen but has no cards in the DOM");
want(!report.inFight || cardBoxes.length === report.cards,
  `${cardBoxes.length} card boxes measured for ${report.cards} card(s)`);'''

OLD_NEG = '''// ---- 6. The negative control ------------------------------------------------------------
// Hide the hand and demand the blob count collapses. Without this, "N blobs == N cards" could be
// satisfied by a detector that counts *anything* (a border, a shadow) as long as the numbers agree.
const negative = await page.evaluate(`(() => {
  const panel = document.getElementById("handPanel");
  panel.style.opacity = "0";
  return getComputedStyle(panel).opacity;
})()`);
const hidden = await page.screenshot();
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
}'''

NEW_NEG = '''// ---- 6. Per card: was **this** card painted? (differential, no colour reference) ----------
// `opacity: 0` on the panel keeps the layout and paints nothing -- exactly the shape of "the DOM says
// five cards and the screen shows none". Asking "did this box change" answers both questions at once:
// a painted card must change, an unpainted one cannot.
const negative = await page.evaluate(`(() => {
  const panel = document.getElementById("handPanel");
  panel.style.opacity = "0";
  return getComputedStyle(panel).opacity;
})()`);
const hidden = await page.screenshot();
const perCardChanged = cardBoxes.map((box) => diffCountIn(shot, hidden, box, 8));
report.negative = {
  opacity: negative,
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
}'''

OLD_IMPORT = '''import {
  colourCount, diffCount, dominantColour, inkCount, inkPerBox, rect, sameBitmap,
} from "./pixels.mjs";'''

NEW_IMPORT = '''import {
  colourCount, diffCount, diffCountIn, dominantColour, inkCount, rect, sameBitmap,
} from "./pixels.mjs";'''

OLD_LOG = '''console.log(`  hand              ${report.handCards} card(s) · ink ${JSON.stringify(report.cardInk)} · ` +
  `blank ${report.blankCards} · below-strip ink ${report.belowInk} · hero badge ink ${report.heroBadgeInk}`);'''

NEW_LOG = '''console.log(`  hand              ${report.handCards} card(s) in ${report.cardBoxes} box(es) · ` +
  `unpainted ${report.blankCards} · below-strip ink ${report.belowInk} · ` +
  `hero badge ink ${report.heroBadgeInk}`);'''

OLD_LOG2 = '''console.log(`  negative control  opacity ${report.negative.opacity} -> ${report.negative.ink} ink ` +
  `in ${report.negative.boxes} box(es), ${report.negative.changed} pixel(s) changed`);'''

NEW_LOG2 = '''console.log(`  negative control  opacity ${report.negative.opacity} -> per card ` +
  `${JSON.stringify(report.negative.perCardChanged)}, ${report.negative.changed} pixel(s) changed`);'''


def main():
    for path, pairs in [
        (PIXELS, [(OLD_PIXELS, NEW_PIXELS)]),
        (GATE, [
            (OLD_HAND, NEW_HAND),
            (OLD_NEG, NEW_NEG),
            (OLD_IMPORT, NEW_IMPORT),
            (OLD_LOG, NEW_LOG),
            (OLD_LOG2, NEW_LOG2),
        ]),
    ]:
        text = io.open(path, encoding="utf-8").read()
        for old, new in pairs:
            assert text.count(old) == 1, (path, text.count(old), old[:60])
            text = text.replace(old, new)
        io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("differential per-card check; no colour reference")


if __name__ == "__main__":
    main()
