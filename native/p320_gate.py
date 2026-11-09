"""§320：内容门认识 `offer_cards:<n>:<filter>`。

三条语义检查（都是"页面上看着对、行为却错"的形状）：

1. `n` 必须 1..=20（`MAX_EVENT_OFFER` 是容量，超了运行层会 `Capacity`）；
2. 口径只有 `any` / `colorless` 两个值（与 `OfferFilter::from_wire` 逐字对应）；
3. **池子凑得出 `n` 张** —— 无色候选只是整张卡池的一部分，写 20 张无色就会在运行层报
   `PoolTooSmall`，而那是"玩家点了才失败"，比内容门红一次贵得多。
"""

import io

PATH = 'native/sts_content_check.py'

OLD_ENTRY = """                if kind == "relic_random":"""

NEW_ENTRY = '''                if kind == "offer_cards":
                    # §320：候选列表（`The Library` 的 20 选 1、`Sensory Stone` 的无色牌）。
                    # `n:filter` 都在词里，`Amount` 无关。
                    parts = (payload or "").split(":")
                    if len(parts) != 2:
                        fail(where, "offer_cards 需要 `<n>:<any|colorless>`，got %r"
                             % (payload,))
                    else:
                        want, pool_name = parts
                        if not want.isdigit() or not (1 <= int(want) <= 20):
                            fail(where, "offer_cards 的张数 %r 不在 1..=20" % (want,))
                        elif pool_name not in OFFER_FILTERS:
                            fail(where, "offer_cards 的池子口径 %r 不是 any / colorless"
                                 % (pool_name,))
                        elif pool_name == "colorless":
                            if len(colorless_ids) < int(want):
                                fail(where, "offer_cards 要 %s 张无色牌，池子只有 %d 张"
                                     % (want, len(colorless_ids)))
                    if entry.get("Amount") not in (0, None):
                        fail(where, "offer_cards 的 Amount 必须是 0（张数与口径在词里）")
                    counts["effects"] += 1
                    continue
                if kind == "relic_random":'''

OLD_CONST = """EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing", "heal_full",
                      "remove_card", "upgrade_card", "transform_card")"""

NEW_CONST = """EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing", "heal_full",
                      "remove_card", "upgrade_card", "transform_card")
# §320：`offer_cards:<n>:<filter>` 的口径 —— 与 `rd-run::state::OfferFilter::from_wire` 逐字对应。
OFFER_FILTERS = ("any", "colorless")"""

OLD_SECTION = """    cards = {c["Id"]: c.get("Rarity") for c in doc.get("Cards") or []}
    relics = {r["Id"] for r in doc.get("Relics") or []}"""

NEW_SECTION = """    cards = {c["Id"]: c.get("Rarity") for c in doc.get("Cards") or []}
    # §320：哪些牌带 `colorless` tag（`Sensory Stone` 的候选池）。
    colorless_ids = {c["Id"] for c in doc.get("Cards") or []
                     if any(t.get("value") == "colorless" for t in c.get("Tags") or [])}
    relics = {r["Id"] for r in doc.get("Relics") or []}"""


def main():
    t = io.open(PATH, encoding='utf-8').read()
    assert t.count(OLD_ENTRY) == 1, 'entry anchor'
    assert t.count(OLD_CONST) == 1, 'const anchor'
    assert t.count(OLD_SECTION) == 1, 'section anchor'
    assert 'offer_cards' not in t, 'already patched'
    t = t.replace(OLD_ENTRY, NEW_ENTRY)
    t = t.replace(OLD_CONST, NEW_CONST)
    t = t.replace(OLD_SECTION, NEW_SECTION)
    io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
    print('content gate patched')


main()
