"""§320：`ui_test.mjs` 加一条候选面板的判据。

`PANEL_STATES` 那张表只表达**顶层按钮**，而候选面板的按钮在**行上**（与 §293 的加牌候选
同形），所以这里单独一段：桌子上的每一行都要带**内核槽号**，而且张数由快照决定
（20 选 1 与 3 选 1 走同一份面板代码 —— 写死 3 的实现在 20 那一侧会红）。
"""

import io

PATH = 'web/ui_test.mjs'

OLD = """  for (const [name, snapshot, kinds, labels, titlePart] of PANEL_STATES) {"""

NEW = '''  // §320: the event's candidate list (`Pending::EventOffer` = 9). Its buttons live on the **rows**
  // (one per candidate), so `PANEL_STATES` -- which only describes top-level buttons -- cannot
  // express it. Two shapes are checked because the panel code is one: `The Library` offers 20,
  // `Sensory Stone` offers 3, and a panel that hard-codes either number must fail on the other.
  for (const count of [20, 3]) {
    const offer = [];
    for (let slot = 0; slot < count; slot++) {
      offer.push({ slot, id: `card_${slot}`, title: `Card ${slot}` });
    }
    const d = P.describe({ ...BASE, kind: 5, pending: 9, eventOffer: offer });
    if ((d.rows || []).length !== count) {
      fail(`offer(${count}): the panel shows ${(d.rows || []).length} rows`);
    }
    if (!d.title.includes(String(count))) {
      fail(`offer(${count}): the title "${d.title}" does not say how many there are`);
    }
    d.rows.forEach((row, index) => {
      if (!row.button || row.button.action.kind !== "event_offer_take") {
        fail(`offer(${count}) row ${index}: no take button`);
      }
      // ★ 槽号必须是**内核**给的那个（快照里的 `slot`），不是数组下标 —— 这里故意把
      // 槽号打乱，按下标取值的实现会红。
      if (row.button.action.slot !== offer[index].slot) {
        fail(`offer(${count}) row ${index}: slot ${row.button.action.slot}, expected ${offer[index].slot}`);
      }
      if (!String(row.label).includes(String(index))) {
        fail(`offer(${count}) row ${index}: label "${row.label}" is not the card's title`);
      }
    });
  }
  // 空候选：面板不该画出一张空桌子（那是一个"点了没反应"的屏）。
  {
    const d = P.describe({ ...BASE, kind: 5, pending: 9, eventOffer: [] });
    if ((d.rows || []).length !== 0) {
      fail("an empty offer draws rows out of nowhere");
    }
  }

  for (const [name, snapshot, kinds, labels, titlePart] of PANEL_STATES) {'''


def main():
    t = io.open(PATH, encoding='utf-8').read()
    assert t.count(OLD) == 1, 'anchor'
    assert 'event_offer_take' not in t, 'already patched'
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t.replace(OLD, NEW))
    print('ui_test.mjs patched')


main()
