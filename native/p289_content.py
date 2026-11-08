"""§289 内容 + 门：`The Colosseum` 的 `MaxFloor` 与独立药水概率。

`fight_relic:<id>` 不进内容（今天的用户 `Masked Bandits` 需要三个名册外的敌人 +
"付光金币"原子，见 `port-plan.md` §289.4）—— 但它的**理由**是真的：
`red_mask` 是 `Event` 稀有度，`pick_relic`/`pick_relic_of_rarity` 都永远抽不到它
（`relic_rarity_is_droppable` 只认三档掉落稀有度）。"就是这一件"是唯一能给出它的形状。
"""
import io
import json

PATH = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'
GATE = 'D:/Vibe/sts-tui/native/sts_content_check.py'
ALL_POOLS = ('Events', 'Events2', 'Events3')


def main():
    doc = json.load(io.open(PATH, encoding='utf-8'))

    # ── ① The Colosseum：只在第二幕上半场（15 行地图的前半）
    for row in doc['EventTables']['Events2']:
        if row['Id'] == 'the_colosseum':
            # wiki："Spawns only in the top half of Act 2."  层号是**本幕内**的行号，
            # 所以前半 = 1..=7（15 行的 ceil(15/2)=8 ⇒ 用 7 保守：第 8 行已经过半）。
            row['MaxFloor'] = 7

    # ── ② 第二场战斗的**独立**药水概率（wiki："sometimes a Potion"）
    for node in doc['EventNodes']:
        if node['Id'] != 'the_colosseum.after':
            continue
        victory = node['Options'][0]
        assert victory['Label'] == 'VICTORY'
        victory['Effects'].append({'Effect': 'fight_potion_chance:40', 'Amount': 0})

    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('content: MaxFloor 7 + fight_potion_chance 40')

    # ── ③ 门：三个新词 + MaxFloor 的校验
    g = io.open(GATE, encoding='utf-8').read()

    old = '''                if kind in ("fight_gold_set", "fight_relic_rarity", "fight_extra_relic"):'''
    new = '''                if kind in ("fight_relic", "fight_potion_chance"):
                    # §289：指名遗物（载荷是遗物 id）与独立药水概率（0..=100）。
                    if kind == "fight_relic":
                        if payload not in relics:
                            fail(where, "fight_relic:%s 不在 Relics 表里" % payload)
                        elif payload not in IMPLEMENTED_RELICS:
                            fail(where, "fight_relic:%s 的效果内核没实现" % payload)
                        counts["relic"] += 1
                    else:
                        if not payload or not payload.isdigit() or int(payload) > 100:
                            fail(where, "fight_potion_chance 需要 0..=100 的整数，got %r"
                                 % (payload,))
                        if entry.get("Amount") not in (0, None):
                            fail(where, "fight_potion_chance 的 Amount 必须是 0（数字在词里）")
                    continue
                if kind in ("fight_gold_set", "fight_relic_rarity", "fight_extra_relic"):'''
    assert g.count(old) == 1, g.count(old)
    g = g.replace(old, new)

    # MaxFloor：与 MinFloor 一起校验（0 / 缺席 = 无界；有界时必须与 MinFloor 同向）
    old2 = '''    for pool in ("Events", "Events2", "Events3"):
        rows = doc.get("EventTables", {}).get(pool) or []'''
    if g.count(old2) == 1:
        g = g.replace(old2, '''    for pool in ("Events", "Events2", "Events3"):
        rows = doc.get("EventTables", {}).get(pool) or []
        for row in rows:
            # §288/§289：事件条目的楼层门槛（缺席 = 无界）。
            low = row.get("MinFloor", 0)
            high = row.get("MaxFloor", 0)
            for key, value in (("MinFloor", low), ("MaxFloor", high)):
                if not isinstance(value, int) or value < 0:
                    fail("EventTables.%s.%s.%s" % (pool, row.get("Id"), key),
                         "must be a non-negative int, got %r" % (value,))
            if high and low and high < low:
                fail("EventTables.%s.%s" % (pool, row.get("Id")),
                     "MaxFloor %d is below MinFloor %d" % (high, low))
            if high and high > 1:
                # 层号是**本幕内**的行号（1..=ROWS），所以上界超过地图长度就是内容错误。
                if high > 15:
                    fail("EventTables.%s.%s.MaxFloor" % (pool, row.get("Id")),
                         "%d is past the act's 15 rows" % high)''')
    else:
        print('WARN: no floor-gate anchor in the gate; skipped')
    io.open(GATE, 'w', encoding='utf-8', newline='\n').write(g)
    print('gate: fight_relic / fight_potion_chance / MaxFloor')


main()
