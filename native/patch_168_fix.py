"""§168: fix the two detectors the fault injection broke.

1. **ink**: "count pixels of the ink colour" cannot tell *text drawn in ink* from *the background being
   ink*. With `--ink` set to the page background the count went **up** (155,223) and the assertion
   passed. The claim has to include legibility: ink must be far from the background, and **then**
   there must be pixels of it.
2. **coverage**: measured over the whole page, hiding the board left 3.2% non-background (the archive
   and replay bars are still there) and the 2% floor passed. The claim is about the **board**: measure
   inside it.
"""
import io

GATE = "web/pixel_test.mjs"

OLD_COVER = """const pageBg = dominantColour(shot, rect(0, 0, shot.width, shot.height));
const pageInk = inkCount(shot, rect(0, 0, shot.width, shot.height), pageBg, 24);
const coverage = pageInk / (shot.width * shot.height);
report.coverage = Number(coverage.toFixed(4));
report.pageBg = pageBg.slice(0, 3).map((v) => v.toString(16).padStart(2, "0")).join("");
// A blank page is 0; a solid fill is 1. Both are failures, and both are cheap to state.
want(coverage > 0.02, `the page is ${(coverage * 100).toFixed(2)}% non-background: it barely painted`);
want(coverage < 0.95, `the page is ${(coverage * 100).toFixed(2)}% non-background: it is a solid fill`);"""

NEW_COVER = """const pageBg = dominantColour(shot, rect(0, 0, shot.width, shot.height));
report.pageBg = pageBg.slice(0, 3).map((v) => v.toString(16).padStart(2, "0")).join("");

// ⚠️ Coverage is measured **inside the board**, not over the page. Measured page-wide, hiding the
// whole board still left 3.2% non-background -- the archive and replay bars at the bottom are page
// furniture and they kept the number above any floor small enough to be honest. (Found by fault
// injection: `fault_pixels.mjs` hides `.board` and asks whether this assertion notices.)
const boardBox = await boxOf(".board");
want(boardBox !== null, "the page has no .board element");
const boardBg = boardBox ? dominantColour(shot, boardBox) : pageBg;
const boardInk = boardBox ? inkCount(shot, boardBox, boardBg, 24) : 0;
const boardArea = boardBox ? Math.max(1, Math.round(boardBox.width) * Math.round(boardBox.height)) : 1;
const coverage = boardInk / boardArea;
report.coverage = Number(coverage.toFixed(4));
report.boardBox = boardBox ? [Math.round(boardBox.width), Math.round(boardBox.height)] : null;
// A blank board is 0; a solid fill is 1. Both are failures, and both are cheap to state.
want(coverage > 0.05, `the board is ${(coverage * 100).toFixed(2)}% non-background: it barely painted`);
want(coverage < 0.95, `the board is ${(coverage * 100).toFixed(2)}% non-background: it is a solid fill`);"""

OLD_INK = """if (inkRgb) {
  const inkPixels = colourCount(shot, rect(0, 0, shot.width, shot.height), inkRgb, 8);
  report.inkPixels = inkPixels;
  want(inkPixels > 500, `only ${inkPixels} pixels are the page's own ink colour -- text is not drawn in it`);
}"""

NEW_INK = """if (inkRgb) {
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
}"""

OLD_IMPORT = """import {
  colourCount, diffCount, diffCountIn, dominantColour, inkCount, rect, sameBitmap,
} from "./pixels.mjs";"""

NEW_IMPORT = """import {
  colourCount, diffCount, diffCountIn, distance, dominantColour, inkCount, rect, sameBitmap,
} from "./pixels.mjs";"""

OLD_LOG = """console.log(`  bitmap            ${report.size} · background #${report.pageBg} · ` +
  `non-background ${(report.coverage * 100).toFixed(2)}%`);"""

NEW_LOG = """console.log(`  bitmap            ${report.size} · background #${report.pageBg} · board ` +
  `${JSON.stringify(report.boardBox)} with ${(report.coverage * 100).toFixed(2)}% non-background`);"""

OLD_LOG_INK = """console.log(`  ink               ${report.ink} -> ${report.inkPixels} pixel(s) in the page's own ink colour`);"""

NEW_LOG_INK = """console.log(`  ink               ${report.ink} (${report.inkGap} from the background) -> ` +
  `${report.inkPixels} pixel(s) drawn in it`);"""


def main():
    text = io.open(GATE, encoding="utf-8").read()
    for old, new in [
        (OLD_COVER, NEW_COVER),
        (OLD_INK, NEW_INK),
        (OLD_IMPORT, NEW_IMPORT),
        (OLD_LOG, NEW_LOG),
        (OLD_LOG_INK, NEW_LOG_INK),
    ]:
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(GATE, "w", encoding="utf-8", newline="").write(text)
    print("coverage is measured on the board; ink has a legibility half")


if __name__ == "__main__":
    main()
