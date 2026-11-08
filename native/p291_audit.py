"""§291 F.5 的审计与修正：`MinGold` 事件门槛 + "付不起就别画"的门判据。

## 审计结论（对着代码与内容逐条查，不看旧表）

F.5 的四条里，三条**已经被后来的节修掉了**，只有旧表没更新：

| F.5 的行 | 现状（证据） | 谁修的 |
|---|---|---|
| 奖赏/赔付时机（结果屏 `[Leave]` 上兑） | `scrap_pile.found` / `the_joust.*_won` 的 `Effects` 在**段**上，`[Leave]` 是空效果 | §286 段的进入效果 |
| `Wing Statue` `[Destroy]` 总是出现 | `Requires: card_damage at_least 10`；起始牌组（单次最高 8）下不画 | §287 |
| `Dead Adventurer` 伏击没载体 | `Fight: "elite"` + `Encounter: "EliteEvent"` + 战后欠账 | §286/§287 |
| `Scrap Ooze` 的遗物稀有度 | `relic_random` → `pick_relic`（50/33/17、排除已持有） | 一直一致 |

## 审计中新发现的**真问题**：`The Joust` 会**卡死**

wiki："This event can only be encountered with **more than 50 Gold**." 而我们的内容：

* `the_joust.offer` 的两个选项都是 `gold_cost:50`，**没有 `Requires`** ⇒ 付不起时按钮**照样画**，
  点下去内核 `-2`（`NotEnoughGold`），屏幕不变；
* 这个事件**没有 `[Leave]`**（wiki 也是"no option to avoid betting"）⇒ **零可用按钮 = 卡死**。

两处修：

1. **`MinGold` 事件门槛**（与 `MinFloor`/`MaxFloor` 同一族的池过滤）：
   `EventTables.Events2` 的 `the_joust` 加 `MinGold: 51` —— 金币 ≤ 50 时这个事件**不出现**，
   正好是 wiki 那句"more than 50 Gold"。
2. **内容门 G1**："付不起就别画" —— 任何带 `gold_cost:<n>` 的选项**必须**带
   `Requires: gold at_least n`。今天只有 `The Joust` 违反（`The Cleric` 早就写对了），
   而这条规则把"死按钮"从"靠人记得"变成"内容门红"。

⚠️ 两条要**一起**才不卡死：只加 `Requires` 会让"金币 ≤ 50 时进来"变成"零按钮"，
只加 `MinGold` 而有人绕过池子（`RD_DEBUG.startAnEvent` / 存档）仍会画死按钮。
"""
import io

CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
WASM = 'D:/Vibe/sts-tui/kernel/rd-wasm/src/run.rs'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'
CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:90])
    return s.replace(old, new)


def main():
    # ── ① rd-core：`MinGold`
    c = io.open(CORE, encoding='utf-8').read()
    c = patch(c, '''    pub fn event_pool_at(&'a self, pool: &str, floor: i32) -> Option<[&'a str; MAX_POOL_IDS]> {''',
'''    pub fn event_pool_at(
        &'a self,
        pool: &str,
        floor: i32,
        gold: i32,
    ) -> Option<[&'a str; MAX_POOL_IDS]> {''')
    c = patch(c, '''            // §289：上界（`The Colosseum` 只在第二幕上半场）。缺席 = 没有上界。
            let mut max_floor = 0i32;''',
'''            // §289：上界（`The Colosseum` 只在第二幕上半场）。缺席 = 没有上界。
            let mut max_floor = 0i32;
            // §291：金币门槛（`The Joust` 只在 >50 金币时出现）。
            let mut min_gold = 0i32;''')
    c = patch(c, '''                } else if sub_name == "MaxFloor" && sub.kind() == F_INT {
                    max_floor = slot_int(element_term.slot(offset)?);
                }''','''                } else if sub_name == "MaxFloor" && sub.kind() == F_INT {
                    max_floor = slot_int(element_term.slot(offset)?);
                } else if sub_name == "MinGold" && sub.kind() == F_INT {
                    min_gold = slot_int(element_term.slot(offset)?);
                }''')
    c = patch(c, '''            if id.is_empty() || floor < min_floor || (max_floor != 0 && floor > max_floor) {''',
'''            if id.is_empty()
                || floor < min_floor
                || (max_floor != 0 && floor > max_floor)
                || gold < min_gold
            {''')
    io.open(CORE, 'w', encoding='utf-8', newline='\n').write(c)
    print('rd-core: MinGold')

    # ── ② wasm：把金币递进去
    w = io.open(WASM, encoding='utf-8').read()
    w = patch(w, '''        let floor = session.state.floor();
        let Some(pool) = image.event_pool_at(pool_name, floor) else {''',
'''        let floor = session.state.floor();
        // §291：`MinGold` 与楼层同一个筛子（`The Joust` 只在 >50 金币时出现）。
        let gold = session.state.gold();
        let Some(pool) = image.event_pool_at(pool_name, floor, gold) else {''')
    io.open(WASM, 'w', encoding='utf-8', newline='\n').write(w)
    print('wasm: gold into the pool filter')

    # ── ③ 内容：The Joust 的两个押注项补 `Requires`，池条目加 `MinGold`
    import json
    doc = json.load(io.open(CONTENT, encoding='utf-8'))
    for node in doc['EventNodes']:
        if node['Id'] != 'the_joust.offer':
            continue
        for option in node['Options']:
            assert option['Label'].startswith(('Murderer', 'Owner')), option['Label']
            option['Requires'] = [{'Kind': 'gold', 'Op': 'at_least', 'Amount': 50}]
    for pool in ('Events', 'Events2', 'Events3'):
        for row in doc['EventTables'][pool]:
            if row['Id'] == 'the_joust':
                row['MinGold'] = 51
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: the_joust MinGold 51 + Requires gold 50')

    # ── ④ 门：`MinGold` 校验 + G1（gold_cost ⇒ Requires）
    g = io.open(GATE, encoding='utf-8').read()
    g = patch(g, '''            low = row.get("MinFloor", 0)
            high = row.get("MaxFloor", 0)''','''            low = row.get("MinFloor", 0)
            high = row.get("MaxFloor", 0)
            min_gold = row.get("MinGold", 0)''')
    g = patch(g, '''            for key, value in (("MinFloor", low), ("MaxFloor", high)):''',
'''            for key, value in (("MinFloor", low), ("MaxFloor", high), ("MinGold", min_gold)):''')
    g = patch(g, '''            if high and low and high < low:''','''            if min_gold and (min_gold < 1 or min_gold > 999):
                fail(where + ".MinGold", "must be 1..=999, got %r" % (min_gold,))
            if high and low and high < low:''')

    # G1：一个选项要**付** n 金币，就必须在付不起时不画（`Requires: gold at_least n`）。
    g = patch(g, '''            for kind_label, key in (("", "Effects"), ("Asc", "EffectsAsc")):
                edits = check_effects(label, option.get(key), kind_label)''',
'''            # §291 G1：**付不起就别画**。一个选项带 `gold_cost:<n>`，就必须带
            # `Requires: gold at_least n` —— 否则按钮照画、点下去内核 `-2`、屏幕不变
            # （`The Joust` 的两个押注项曾经就是这样，而它没有 `[Leave]` ⇒ 卡死）。
            for key in ("Effects", "EffectsAsc"):
                for spec in option.get(key) or []:
                    word = spec.get("Effect") or ""
                    if not word.startswith("gold_cost:"):
                        continue
                    try:
                        price = int(word.split(":", 1)[1])
                    except ValueError:
                        continue            # 词法错误由 check_effects 报
                    reqs = option.get("Requires") or option.get("RequiresAsc") or []
                    covered = any(
                        r.get("Kind") == "gold" and r.get("Op") == "at_least"
                        and isinstance(r.get("Amount"), int)
                        and r.get("Amount") >= price
                        for r in reqs
                    )
                    if not covered:
                        fail(label, "pays %d gold but has no `Requires: gold at_least %d` -- "
                                    "the button would be drawn and then refused"
                             % (price, price))
            for kind_label, key in (("", "Effects"), ("Asc", "EffectsAsc")):
                edits = check_effects(label, option.get(key), kind_label)''')
    io.open(GATE, 'w', encoding='utf-8', newline='\n').write(g)
    print('gate: MinGold + G1')


main()
