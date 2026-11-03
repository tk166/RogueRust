"""§194 act-3 bosses: Awakened One (300 HP, two phases) and Donu & Deca (a pair, 250 HP each).

Wiki text: `native/wiki_asc/awakened_one.txt`, `native/wiki_asc/donu_and_deca.txt`.
"""
from p194_helpers import (
    action, allies, block, card_to_discard, c_all, c_counter, c_health, const, current_health,
    drop_status, heal, hit, max_health, maximum, rule, set_counter, source, status, subtract,
)

ACTIONS = [
    # ---------------------------------------------------------------- Awakened One
    action("awakened_one.slash", "Slash", "Slash - 20 damage", "Attack", [hit(20)]),
    action("awakened_one.soul_strike", "Soul Strike", "Soul Strike - 6 damage x4", "Attack",
           [hit(6), hit(6), hit(6), hit(6)]),
    # Rebirth is the wiki's "heals to full HP, removes all Debuffs, loses Curiosity". The heal is
    # `max(maxHealth - currentHealth, 0)` -- `max` exists precisely so a Heal cannot go negative.
    # Curiosity is dropped by name because there is no "clear all statuses" node.
    action("awakened_one.rebirth", "Rebirth", "Rebirth - heals to full, loses Curiosity", "Special",
           [heal(maximum(subtract(max_health(source()), current_health(source())), const(0))),
            drop_status("standard.curiosity"),
            set_counter("ao_phase", 1), set_counter("ao_started", 0), set_counter("ao_toggle", 0)]),
    action("awakened_one.dark_echo", "Dark Echo", "Dark Echo - 40 damage", "Attack",
           [hit(40), set_counter("ao_started", 1), set_counter("ao_toggle", 0)]),
    action("awakened_one.tackle", "Tackle", "Tackle - 10 damage x3", "Attack",
           [hit(10), hit(10), hit(10), set_counter("ao_toggle", 1)]),
    action("awakened_one.sludge", "Sludge", "Sludge - 18 damage, 1 Void into your draw pile", "Attack",
           [hit(18), card_to_discard("void", 1), set_counter("ao_toggle", 0)]),

    # ---------------------------------------------------------------- Donu
    action("donu.circle_of_power", "Circle of Power", "Circle of Power - allies +3 Strength", "Buff",
           [status("standard.strength", 3, allies())]),
    action("donu.beam", "Beam", "Beam - 10 damage x2", "Attack",
           [hit(10), hit(10)], [(4, lambda: [hit(12), hit(12)])]),

    # ---------------------------------------------------------------- Deca
    action("deca.beam", "Beam", "Beam - 10 damage x2, 2 Dazed into your discard pile",
           "Debuff", [hit(10), hit(10), card_to_discard("dazed", 2)],
           [(4, lambda: [hit(12), hit(12), card_to_discard("dazed", 2)])]),
    action("deca.square_of_protection", "Square of Protection",
           "Square of Protection - allies gain 16 Block", "Defend",
           [block(16, allies())],
           [(19, lambda: [block(16, allies()), status("standard.plated_armor", 3, allies())])]),
]


AWAKENED_ONE = dict(
    id="awakened_one",
    name="Awakened One",
    hp=300,
    # Slash cannot come three times in a row, Soul Strike cannot come twice: L = slash, slash, soul,
    # slash -> the sequence is slash,slash,soul,slash,slash,soul... i.e. 75%/25% and never 3 in a
    # row. Round 1 is Slash, as the wiki says.
    actions=["awakened_one.slash", "awakened_one.slash", "awakened_one.soul_strike",
             "awakened_one.slash"],
    starting=[
        {"StatusDefinitionId": {"value": "standard.regen"}, "Stacks": 10},
        {"StatusDefinitionId": {"value": "standard.curiosity"}, "Stacks": 1},
    ],
    rules=[
        # "Once its HP reaches 0 it revives." There is no death interceptor, so the *intent* becomes
        # Rebirth at <= 25% and the heal lands before the killing blow. Stated, not hidden.
        rule(c_all([c_health("LessOrEqual", 25), c_counter("ao_phase", "LessOrEqual", 0)]),
             "awakened_one.rebirth", 90),
        rule(c_all([c_counter("ao_phase", "GreaterOrEqual", 1),
                    c_counter("ao_started", "LessOrEqual", 0)]),
             "awakened_one.dark_echo", 85),
        rule(c_all([c_counter("ao_phase", "GreaterOrEqual", 1),
                    c_counter("ao_toggle", "LessOrEqual", 0)]),
             "awakened_one.tackle", 80),
        rule(c_all([c_counter("ao_phase", "GreaterOrEqual", 1),
                    c_counter("ao_toggle", "GreaterOrEqual", 1)]),
             "awakened_one.sludge", 80),
    ],
    note="§194：wiki 数值（HP 300/320；Regenerate 10 / A19 15；Curiosity 1 / A19 2；Slash 20；"
         "Soul Strike 6×4；Dark Echo 40；Tackle 10×3；Sludge 18 + 1 Void）。两阶段用计数器做："
         "`ao_phase` 由 Rebirth 置 1，之后 Dark Echo（一次）→ Tackle/Sludge 交替。"
         "⚠️ 偏差：① Rebirth 在 **HP ≤ 25%** 时改为意图（内核没有死亡拦截，死亡后无法复活）；"
         "② 『移除所有 debuff』只按名摘掉 Curiosity（没有『清空状态』节点）；③ 两个 Cultist 不在"
         "（wiki 的第二阶段会在场）；④ Regenerate/Curiosity 的层数不随 A19 变（`StartingStatuses`"
         " 没有升档轴）。",
)

DONU = dict(
    id="donu",
    name="Donu",
    hp=250,
    actions=["donu.circle_of_power", "donu.beam"],
    starting=[{"StatusDefinitionId": {"value": "standard.artifact"}, "Stacks": 2}],
    rules=[],
    note="§194：wiki 数值（HP 250/265；Artifact 2 / A19 3；Circle of Power 全体 +3 Str；"
         "Beam 10×2→A4 12×2）。⚠️ 偏差：Artifact 层数不随 A19 变；『全体』用 `sel.allAllies`。",
)

DECA = dict(
    id="deca",
    name="Deca",
    hp=250,
    actions=["deca.beam", "deca.square_of_protection"],
    starting=[{"StatusDefinitionId": {"value": "standard.artifact"}, "Stacks": 2}],
    rules=[],
    note="§194：wiki 数值（HP 250/265；Artifact 2 / A19 3；Beam 10×2→A4 12×2 + 2 Dazed；"
         "Square of Protection 全体 16 Block，A19 另给 3 Plated Armor）。"
         "⚠️ 偏差：Artifact 层数不随 A19 变。",
)
