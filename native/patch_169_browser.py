"""browser_test.mjs: scenario (k) -- 存档 / 回档，走页面上的按钮，不走 ABI。

What it proves, in the order a player does it:
 1. 复制档案 fills the text box with **one line** starting `RDA1-`;
 2. start a **different** run (so a stale state cannot pass), paste, 回档;
 3. the restored run is the old one: floor / hp / gold / deck all come back;
 4. a single edited character is **refused**, and the page says so (that is the whole point of the
    CRC: "回档被拒" must be visible, not a wrong game).
"""
import io

PATH = "web/browser_test.mjs"

ANCHOR = """  // §159: (seed, level) is the whole description of a run."""

BLOCK = '''  // (k) **§161.9: the one-line archive.**
  window.RD_DEBUG.startWithSeed(4321, 0);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  // Walk two nodes so the saved run is not the state a fresh start would give.
  for (let hop = 0; hop < 2; hop++) {
    const lit = [...document.querySelectorAll("#mapbox g.node.reachable")];
    if (!lit.length) break;
    lit[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await sleep(0);
    const first = panel().querySelector("[data-panel-action]:not([disabled])");
    if (first) first.click();
    await sleep(0);
    if (!document.getElementById("handPanel").hidden) break; // a fight is live: archive refuses
  }
  out.archiveFloor = ex.rd_run_observe(0);
  out.archiveHp = ex.rd_run_observe(2);
  out.archiveGold = ex.rd_run_observe(4);
  out.archiveDeck = ex.rd_run_deck_count();
  out.archiveInFight = !document.getElementById("handPanel").hidden;
  document.getElementById("archiveCopy").onclick();
  await sleep(0);
  const saved = document.getElementById("archiveBox").value;
  out.archiveText = saved.slice(0, 9);
  out.archiveLength = saved.length;
  out.archiveLines = saved.split("\\n").length;
  out.archiveNote = text(document.getElementById("archiveNote"));
  out.archiveRefusedInFight = out.archiveInFight ? saved.length : -1;

  // A fresh, different run: (4322) rather than (4321), so nothing can pass by accident.
  window.RD_DEBUG.startWithSeed(4322, 0);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  out.archiveSeedAfterRestart = ex.rd_run_seed();

  // Paste and restore through the page's own button.
  document.getElementById("archiveBox").value = saved;
  document.getElementById("archiveRestore").onclick();
  await sleep(0);
  out.restoredSeed = ex.rd_run_seed();
  out.restoredFloor = ex.rd_run_observe(0);
  out.restoredHp = ex.rd_run_observe(2);
  out.restoredGold = ex.rd_run_observe(4);
  out.restoredDeck = ex.rd_run_deck_count();
  out.restoredNote = text(document.getElementById("archiveNote"));

  // One edited character must be **refused**, and the run must not move.
  const edited = saved.slice(0, 12) + (saved[12] === "A" ? "B" : "A") + saved.slice(13);
  document.getElementById("archiveBox").value = edited;
  document.getElementById("archiveRestore").onclick();
  await sleep(0);
  out.editedRefused = /被拒/.test(text(document.getElementById("archiveNote")));
  out.afterEditFloor = ex.rd_run_observe(0);
  out.afterEditSeed = ex.rd_run_seed();

  // …and the same run saved twice is the same string.
  document.getElementById("archiveCopy").onclick();
  await sleep(0);
  out.archiveStable = document.getElementById("archiveBox").value === saved;

'''

CHECKS = """// §161.9: the one-line archive, through the page's own buttons.
want(report.archiveInFight === false, "an archive was taken mid-fight (this scenario must not)");
want(report.archiveText === "RDA1-".concat(report.archiveText.slice(5)) ,
  `the archive does not start with RDA1- (${JSON.stringify(report.archiveText)})`);
want(report.archiveLength > 100, `the archive is suspiciously short (${report.archiveLength})`);
want(report.archiveLines === 1, `the archive is ${report.archiveLines} lines, expected one`);
want(/已复制|剪贴板/.test(report.archiveNote || ""),
  `copy said nothing useful: ${JSON.stringify(report.archiveNote)}`);
want(report.archiveSeedAfterRestart === 4322,
  `the restart did not change the seed (${report.archiveSeedAfterRestart})`);
want(report.restoredSeed === 4321, `restore gave seed ${report.restoredSeed}, expected 4321`);
want(report.restoredFloor === report.archiveFloor,
  `floor ${report.restoredFloor} != ${report.archiveFloor}`);
want(report.restoredHp === report.archiveHp, `hp ${report.restoredHp} != ${report.archiveHp}`);
want(report.restoredGold === report.archiveGold,
  `gold ${report.restoredGold} != ${report.archiveGold}`);
want(report.restoredDeck === report.archiveDeck,
  `deck ${report.restoredDeck} != ${report.archiveDeck}`);
want(report.editedRefused === true, "an edited archive was accepted");
want(report.afterEditFloor === report.restoredFloor,
  "a refused restore moved the run anyway (that is the worse bug)");
want(report.afterEditSeed === 4321, "a refused restore changed the seed");
want(report.archiveStable === true, "the same run produced two different archives");

"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "archiveCopy" not in text, "already inserted"
    text = text.replace(ANCHOR, BLOCK + ANCHOR)

    anchor2 = "await page.close();"
    assert text.count(anchor2) == 1
    text = text.replace(anchor2, CHECKS + anchor2)

    old = 'console.log("  attack potion     " + report.apTitle'
    assert text.count(old) == 1
    text = text.replace(old, '''console.log("  archive           " + report.archiveText + "… · " +
  report.archiveLength + " chars · " + report.archiveLines + " line(s) · restored floor " +
  report.restoredFloor + " hp " + report.restoredHp + " gold " + report.restoredGold +
  " · edited refused " + report.editedRefused);
''' + old)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("browser_test: scenario (k)")


if __name__ == "__main__":
    main()
