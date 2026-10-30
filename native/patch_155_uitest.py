"""§155: assert the relic reward **row** in `ui_test.mjs` (the footer-button loop cannot see rows).

Written from a file because the payload contains `${...}`, backticks and `||`, which PowerShell's
single-quoted heredoc mangles.
"""

import io

PATH = r"D:\Vibe\sts-tui\web\ui_test.mjs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()

ANCHOR = """{
  for (const [name, snapshot, kinds, labels, titlePart] of PANEL_STATES) {"""

BLOCK = '''{
  // §155: the relic reward is a **row**, so the footer-button loop below cannot see it. Assert the
  // row's own action -- otherwise the relic would be drawn with a button that does nothing (§150).
  const withRelic = P.describe({ ...BASE, kind: 2, pending: 4, rewardGold: 30,
    rewardCards: [{ id: "anger", title: "Anger", chip: "" }], rewardRelic: "vajra" });
  const relicRow = (withRelic.rows || []).find((row) => String(row.label).includes("遗物"));
  if (!relicRow) fail("a reward with a relic draws no 遗物 row");
  if (String(relicRow.label).indexOf("vajra") < 0) {
    fail("the relic row does not name the relic: " + JSON.stringify(relicRow.label));
  }
  if (!relicRow.button || relicRow.button.action.kind !== "take_relic") {
    fail("the relic row's button is " + JSON.stringify(relicRow.button) + ", expected take_relic");
  }
  if (String(relicRow.button.label).indexOf("拿") < 0) {
    fail("the relic row's button says " + JSON.stringify(relicRow.button.label));
  }
  // ...and a normal fight must not draw one.
  const noRelic = P.describe({ ...BASE, kind: 1, pending: 4, rewardGold: 12,
    rewardCards: [{ id: "anger", title: "Anger", chip: "" }] });
  if ((noRelic.rows || []).some((row) => String(row.label).includes("遗物"))) {
    fail("a normal fight drew a relic row");
  }

  for (const [name, snapshot, kinds, labels, titlePart] of PANEL_STATES) {'''

if "relicRow" in source:
    print("relic row assertion already present")
else:
    if ANCHOR not in source:
        raise SystemExit("anchor missing")
    source = source.replace(ANCHOR, BLOCK, 1)
    with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    print("relic row assertion inserted")
