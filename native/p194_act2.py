"""§194 act-2 bosses: Bronze Automaton (300 HP + 2 orbs) and The Collector (282 HP + 2 Torch Heads).

Wiki text: `native/wiki_asc/bronze_automaton.txt`, `native/wiki_asc/the_collector.txt`.
"""
from p194_helpers import (
    action, allies, block, c_all, c_asc, c_rounds, hit, rule, status,
)

ACTIONS = [
    # ---------------------------------------------------------------- Bronze Automaton
    action("bronze_automaton.flail", "Flail", "Flail - 7 damage x2", "Attack",
           [hit(7), hit(7)], [(4, lambda: [hit(8), hit(8)])]),
    # "Gains (3;Asc|4|4) Strength and (9;Asc|9|12) Block": **two independent thresholds on one
    # move**, which is exactly what §192's variant list is for -- the A9 entry repeats the A4
    # Strength number because only the highest eligible variant is used.
    action("bronze_automaton.boost", "Boost", "Boost - 3 Strength, 9 Block", "Defend",
           [status("standard.strength", 3, "source"), block(9)],
           [(4, lambda: [status("standard.strength", 4, "source"), block(9)]),
            (9, lambda: [status("standard.strength", 4, "source"), block(12)])]),
    action("bronze_automaton.hyper_beam", "HYPER BEAM", "HYPER BEAM - 45 damage", "Attack",
           [hit(45)], [(4, lambda: [hit(50)])]),
    action("bronze_automaton.stunned", "Stunned", "Stunned - no effect", "Special", []),
    # Bronze Orb. `Stasis` (steal a card, give it back when the orb dies) has no primitive in this
    # kernel: there is no way to take a card out of a pile into a combatant and hand it back.
    action("bronze_orb.beam", "Beam", "Beam - 8 damage", "Attack", [hit(8)]),
    action("bronze_orb.support_beam", "Support Beam", "Support Beam - allies gain 12 Block", "Defend",
           [block(12, allies())]),

    # ---------------------------------------------------------------- The Collector
    action("the_collector.fireball", "Fireball", "Fireball - 18 damage", "Attack",
           [hit(18)], [(4, lambda: [hit(21)])]),
    # "All enemies gain (3;Asc|4|4;Asc|19|5) Strength. Gains (15;Asc|9|18;Asc|19|23) Block."
    # Three thresholds, one of them on each half -> three variants, each repeating the earlier ones.
    action("the_collector.buff", "Buff", "Buff - allies +3 Strength, 15 Block", "Defend",
           [status("standard.strength", 3, allies()), block(15)],
           [(4, lambda: [status("standard.strength", 4, allies()), block(15)]),
            (9, lambda: [status("standard.strength", 4, allies()), block(18)]),
            (19, lambda: [status("standard.strength", 5, allies()), block(23)])]),
    action("the_collector.mega_debuff", "Mega Debuff", "Mega Debuff - 3 Weak, 3 Vulnerable, 3 Frail",
           "Debuff",
           [status("standard.weak", 3), status("standard.vulnerable", 3), status("standard.frail", 3)],
           [(19, lambda: [status("standard.weak", 5), status("standard.vulnerable", 5),
                          status("standard.frail", 5)])]),
    action("torch_head.tackle", "Tackle", "Tackle - 7 damage", "Attack", [hit(7)]),
]

AUTOMATON = dict(
    id="bronze_automaton",
    name="Bronze Automaton",
    hp=300,
    # The wiki's order after "Spawn Orbs": flail, boost, flail, boost, HYPER BEAM, Stunned -- and the
    # orbs are already on the field (see the deviation), so the cycle starts at Flail on turn 1.
    actions=["bronze_automaton.flail", "bronze_automaton.boost", "bronze_automaton.flail",
             "bronze_automaton.boost", "bronze_automaton.hyper_beam", "bronze_automaton.stunned"],
    starting=[{"StatusDefinitionId": {"value": "standard.artifact"}, "Stacks": 3}],
    rules=[
        # A19: "always uses Boost in place of Stunned". Stunned sits at rounds 6, 12, 18, 24 of the
        # 6-cycle, and `anyOf` of concrete round numbers is how a modulo is spelled without one
        # (`intent.round` has no remainder; `remainder` has no evaluator).
        rule(c_all([c_asc(19), c_rounds([6, 12, 18, 24])]), "bronze_automaton.boost", 60),
    ],
    note="§194：wiki 数值（HP 300/320；Artifact 3；Flail 7×2→A4 8×2；Boost 3 Str + 9 Block，"
         "A4 Str 4、A9 Block 12；HYPER BEAM 45→A4 50；Stunned；A19 用 Boost 顶替 Stunned）。"
         "⚠️ 偏差：两只 Bronze Orb **开局就在场上**（`intent::locate_enemy` 要靠遭遇名单给召唤物找"
         "招式表 ⇒ 列了就会生成，§138），所以 wiki 的 Spawn Orbs 被去掉；`Stasis`（偷牌、死亡时归还）"
         "没有原语，未实现。",
)

ORB = dict(
    id="bronze_orb",
    name="Bronze Orb",
    hp=52,
    actions=["bronze_orb.beam", "bronze_orb.support_beam"],
    starting=[],
    rules=[],
    note="§194：wiki 数值（HP 52-58；Beam 8；Support Beam 给友军 12 Block）。"
         "⚠️ 偏差：Support Beam 用 `sel.allAllies`，即**全体友军**（含自己）；`Stasis` 未实现；"
         "wiki 的 75%/70% 权重与『同一招不连续三次』变成了确定性 2 循环。",
)

COLLECTOR = dict(
    id="the_collector",
    name="The Collector",
    hp=282,
    # wiki: fireball 45~70%, buff 30~15%; the two Torch Heads start on the field (deviation above),
    # so the cycle is a 1:1 alternating pair -- the "cannot buff twice / cannot fireball 3x" rules
    # hold automatically.
    actions=["the_collector.fireball", "the_collector.buff"],
    starting=[],
    rules=[rule(c_rounds([4]), "the_collector.mega_debuff", 60)],
    note="§194：wiki 数值（HP 282/300；Fireball 18→A4 21；Buff 全体 +3 Str + 15 Block，A4 Str 4、"
         "A9 Block 18、A19 5/23；Mega Debuff 3/3/3，A19 5/5/5，第 4 回合必出）。"
         "⚠️ 偏差：两只 Torch Head 开局在场上，Spawn 被去掉（同 Automaton 的理由）；"
         "25/45/30 权重变成确定性 2 循环。",
)

TORCH_HEAD = dict(
    id="torch_head",
    name="Torch Head",
    hp=38,
    actions=["torch_head.tackle"],
    starting=[],
    rules=[],
    note="§194：wiki 数值（HP 38-40；Tackle 7）。"
         "⚠️ 偏差：开局即在场上（wiki 由 Collector 召唤），且不会被再次召唤。",
)
