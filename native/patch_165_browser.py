"""browser_test.mjs: scenario (j) -- the offered-candidate picker (Attack Potion).

The three candidates are **definitions**, not cards: the picker must still be able to render them
(through zone 3), the sentence must say what it says ("from three candidates"), and answering must
add exactly one free card. All three are invisible without a DOM.
"""
import io

PATH = "web/browser_test.mjs"

ANCHOR = """  // §159: (seed, level) is the whole description of a run."""

BLOCK = '''  // (j) **§161.5: three candidates.** Attack Potion offers three *definitions* that do not exist as
  // cards yet. The picker renders them through the same pile exports (zone 3), so the two things
  // worth checking are that the three faces are really there and that the sentence says where they
  // came from -- `kind` alone cannot tell this from Liquid Memories.
  out.apGranted = window.RD_DEBUG.givePotion("attack_potion");
  out.apFight = !document.getElementById("handPanel").hidden;
  const apButton = document.querySelector(
    '[data-use-potion="' + (ex.rd_run_potion_count() - 1) + '"]');
  out.apHasUse = Boolean(apButton);
  if (apButton) {
    try { apButton.onclick(); out.apThrew = null; } catch (error) { out.apThrew = String(error); }
    await sleep(0);
  }
  out.apPending = ex.rd_env_choice_pending();
  out.apSource = ex.rd_env_choice_source();
  out.apKind = ex.rd_env_choice_kind();
  out.apTitle = text(document.getElementById("modalTitle"));
  out.apOptions = document.querySelectorAll("#modalBody [data-choice]").length;
  // Every face must be a real attack with a title -- a definition that the picker cannot name
  // would render as an empty button.
  out.apFaces = [...document.querySelectorAll("#modalBody [data-choice]")]
    .map((el) => text(el)).filter((label) => label.length > 2);
  const cardsBefore = (() => {
    const buf = ex.rd_env_scratch_buf();
    ex.rd_env_observe_into(buf);
    return new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len())[10];
  })();
  const apOption = document.querySelector("#modalBody [data-choice]");
  if (apOption) { apOption.click(); await sleep(0); }
  const apConfirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  if (apConfirm) {
    try { apConfirm.onclick(); out.apConfirmThrew = null; } catch (error) { out.apConfirmThrew = String(error); }
    await sleep(0);
    await sleep(0);
  }
  out.apPendingAfter = ex.rd_env_choice_pending();
  {
    const buf = ex.rd_env_scratch_buf();
    ex.rd_env_observe_into(buf);
    const obsNow = new Int32Array(ex.memory.buffer, buf, ex.rd_env_observe_len());
    out.apHandAfter = obsNow[10];
    out.apCosts = [];
    for (let slot = 0; slot < Math.min(obsNow[10], 10); slot++) {
      out.apCosts.push(obsNow[OFF_HAND + slot * 4 + 1]);
    }
  }
  out.apHandGrew = out.apHandAfter === cardsBefore + 1;
  out.apFreeShown = out.apCosts.filter((cost) => cost === 0).length;

'''

CHECKS = """// §161.5: three offered candidates, one card created, and it is free.
want(report.apFight === true, "could not reach a fight for the Attack Potion check");
want(report.apGranted === 0, `the debug grant failed for attack_potion (${report.apGranted})`);
want(report.apHasUse === true, "Attack Potion offered no 用 button");
want(report.apThrew === null, `the Attack Potion button threw: ${report.apThrew}`);
want(report.apPending === 1, `drinking it opened no question (pending ${report.apPending})`);
want(report.apSource === 2, `the source is not "offered" (source ${report.apSource})`);
want(report.apKind === 3, `the question is not a take-into-hand (kind ${report.apKind})`);
want(/候选/.test(report.apTitle || ""),
  `the picker does not say the cards are candidates: ${JSON.stringify(report.apTitle)}`);
want(report.apOptions === 3, `the picker offered ${report.apOptions} cards, expected 3`);
want(report.apFaces.length === 3,
  `only ${report.apFaces.length} of the three candidates rendered a name`);
want(report.apConfirmThrew === null, `confirm threw: ${report.apConfirmThrew}`);
want(report.apPendingAfter === 0, "confirming did not answer the question");
want(report.apHandGrew === true, "the hand did not grow by exactly one card");
want(report.apFreeShown >= 1,
  `no card reads 0 after the Attack Potion (costs ${JSON.stringify(report.apCosts)})`);

"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "apPending" not in text, "already inserted"
    text = text.replace(ANCHOR, BLOCK + ANCHOR)

    anchor2 = "await page.close();"
    assert text.count(anchor2) == 1
    text = text.replace(anchor2, CHECKS + anchor2)

    old = '''console.log("  liquid memories   " + report.lmTitle'''
    assert text.count(old) == 1
    text = text.replace(old, '''console.log("  attack potion     " + report.apTitle + " · " + report.apOptions +
  " option(s) · hand +1 " + report.apHandGrew + " · free shown " + report.apFreeShown);
console.log("  liquid memories   " + report.lmTitle''')

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("browser_test: scenario (j)")


if __name__ == "__main__":
    main()
