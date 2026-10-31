"""browser_test.mjs: scenario (h) — the §161.3 card-choice picker, driven through the page.

This is the run the review's step 3 asks for: **deterministic**, on the real DOM, through the
controls a player presses. Four things can be wrong here and none of them is visible without a
browser:

  * the picker never opens (the potion is drunk and the page just sits there);
  * a tick does not reach the kernel (`rd_env_choice_pick` mis-wired);
  * confirm does nothing, or throws inside the event handler (§150's shape);
  * the modal can be dismissed while the kernel is still waiting, which leaves a page with an
    empty action table and no way forward.

The potion is put on the belt by `RD_DEBUG.givePotion` -- Elixir is two of twenty-two potions and
a 40% drop, so hoping for one would make this a lottery rather than a check.
"""
import io

PATH = "web/browser_test.mjs"

ANCHOR = """  // §159: (seed, level) is the whole description of a run."""

SCENARIO = '''  // (h) **§161.3: the card-choice picker.** Elixir and Gambler's Brew do not resolve when drunk --
  // they ask a question, and the kernel's action table is empty until it is answered. Every part of
  // that sentence is a separate way to be broken, and all of them are invisible without a browser.
  out.choiceSeed = 31;
  window.RD_DEBUG.startWithSeed(out.choiceSeed);
  await sleep(0);
  panel().querySelector("[data-panel-action]").click();
  await sleep(0);
  if (ex.rd_run_pending() === 7) {
    panel().querySelector("[data-panel-action]").click();
    await sleep(0);
    const pick = document.querySelector("#modalBody [data-pick]");
    if (pick) { pick.click(); await sleep(0); }
  }
  out.choiceFight = await walkIntoFight();
  out.choiceGranted = window.RD_DEBUG.givePotion("elixir");
  out.choiceBelt = ex.rd_run_potion_count();
  // The 用 button of the **last** belt slot, which is the Elixir we just put there.
  const elixirButton = document.querySelector(`[data-use-potion="${out.choiceBelt - 1}"]`);
  out.choiceHasUse = Boolean(elixirButton);
  out.choiceModalBefore = document.getElementById("modal").hidden;
  if (elixirButton) {
    // Call the handler **directly**: a throw inside an event handler never reaches the caller
    // (`dispatchEvent` swallows it into window.onerror), which is exactly how §150 stayed invisible.
    try {
      elixirButton.onclick();
      out.choiceThrew = null;
    } catch (error) {
      out.choiceThrew = String(error);
    }
    await sleep(0);
  }
  out.choicePending = ex.rd_env_choice_pending();
  out.choiceKind = ex.rd_env_choice_kind();
  out.choiceModalOpen = !document.getElementById("modal").hidden;
  out.choiceTitle = text(document.getElementById("modalTitle"));
  out.choiceOptions = document.querySelectorAll("#modalBody [data-choice]").length;
  out.choiceEnvActions = ex.rd_env_action_count();
  // The modal must not be dismissable: an unanswered question with an empty action table is a
  // page with no way forward.
  document.getElementById("modalClose").click();
  await sleep(0);
  out.choiceStillOpen = !document.getElementById("modal").hidden;
  // Tick one option through the **DOM button**, then confirm through the DOM button.
  const exhaustBefore = ex.rd_env_pile_len(2);
  const first = document.querySelector("#modalBody [data-choice]");
  if (first) { first.click(); await sleep(0); }
  out.choiceTicked = first ? first.dataset.ticked : null;
  const choiceConfirm = document.querySelector('#modalBody [data-panel-action="choice-confirm"]');
  out.choiceHasConfirm = Boolean(choiceConfirm);
  if (choiceConfirm) {
    try {
      choiceConfirm.onclick();
      out.choiceConfirmThrew = null;
    } catch (error) {
      out.choiceConfirmThrew = String(error);
    }
    await sleep(0);
    await sleep(0);
  }
  out.choicePendingAfter = ex.rd_env_choice_pending();
  out.choiceExhausted = ex.rd_env_pile_len(2) - exhaustBefore;
  out.choiceEnvActionsAfter = ex.rd_env_action_count();

'''

CHECKS = """// §161.3: the card-choice picker, on the real DOM.
want(report.choiceFight === true, "could not reach a fight to open the card choice in");
want(report.choiceGranted === 0, `the debug potion grant failed (${report.choiceGranted})`);
want(report.choiceHasUse === true, "an Elixir on the belt offered no 用 button in a fight");
want(report.choiceThrew === null, `the Elixir button threw: ${report.choiceThrew}`);
want(report.choicePending === 1, `drinking Elixir opened no question (pending ${report.choicePending})`);
want(report.choiceKind === 1, `the question is not an exhaust (kind ${report.choiceKind})`);
want(report.choiceModalOpen === true, "the picker did not open");
want(/消耗/.test(report.choiceTitle || ""),
  `the picker does not say what it does: ${JSON.stringify(report.choiceTitle)}`);
want(report.choiceOptions >= 2,
  `the picker offered ${report.choiceOptions} cards, expected the whole hand`);
want(report.choiceEnvActions === 0,
  `the action table has ${report.choiceEnvActions} entries while a question is open`);
want(report.choiceStillOpen === true, "the picker closed with the question still open");
want(report.choiceTicked === "1", `clicking an option did not tick it (${report.choiceTicked})`);
want(report.choiceHasConfirm === true, "the picker has no confirm button");
want(report.choiceConfirmThrew === null, `confirm threw: ${report.choiceConfirmThrew}`);
want(report.choicePendingAfter === 0, "confirming did not answer the question");
want(report.choiceExhausted === 1, `confirming exhausted ${report.choiceExhausted} cards, expected 1`);
want(report.choiceEnvActionsAfter > 0, "the action table did not come back after the answer");

"""


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert text.count(ANCHOR) == 1, text.count(ANCHOR)
    assert "choicePending" not in text, "already inserted"
    text = text.replace(ANCHOR, SCENARIO + ANCHOR)

    anchor = """await page.close();"""
    assert text.count(anchor) == 1, text.count(anchor)
    text = text.replace(anchor, CHECKS + anchor)

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("browser_test.mjs: scenario (h) inserted")


if __name__ == "__main__":
    main()
