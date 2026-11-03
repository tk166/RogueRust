"""§194 act-1 bosses: The Guardian (240 HP) and Hexaghost (250 HP).

Wiki text: `native/wiki_asc/the_guardian.txt`, `native/wiki_asc/hexaghost.txt`.
"""
from p194_helpers import (
    action, add, allies, block, card_to_discard, const, c_all, c_counter, c_health, c_round,
    current_health, divide, drop_status, hero, hit, repeat, rule, set_counter, stacks_of, status,
)

ACTIONS = [
    # ---------------------------------------------------------------- The Guardian
    action("the_guardian.charging_up", "Charging Up", "Charging Up - 9 Block", "Defend",
           [block(9)]),
    action("the_guardian.fierce_bash", "Fierce Bash", "Fierce Bash - 32 damage", "Attack",
           [hit(32)], [(4, lambda: [hit(36)])]),
    action("the_guardian.vent_steam", "Vent Steam", "Vent Steam - 2 Weak, 2 Vulnerable", "Debuff",
           [status("standard.weak", 2), status("standard.vulnerable", 2)]),
    # The wiki's post-Mode-Shift sequence ends with Whirlwind, after which the offensive pattern
    # restarts. Resetting the two mode counters inside Whirlwind does both jobs: at the end of the
    # defensive trio (mode 0, step 0 -> the cycle resumes) and as a no-op in the offensive cycle.
    action("the_guardian.whirlwind", "Whirlwind", "Whirlwind - 5 damage x4", "Attack",
           [hit(5), hit(5), hit(5), hit(5),
            set_counter("guard_mode", 0), set_counter("guard_step", 0)]),
    action("the_guardian.defensive_mode", "Defensive Mode", "Defensive Mode - 20 Block, 3 Sharp Hide",
           "Buff",
           [block(20), status("standard.sharp_hide", 3, "source"),
            set_counter("guard_mode", 1), set_counter("guard_step", 0)],
           [(19, lambda: [block(20), status("standard.sharp_hide", 4, "source"),
                          set_counter("guard_mode", 1), set_counter("guard_step", 0)])]),
    action("the_guardian.roll_attack", "Roll Attack", "Roll Attack - 9 damage", "Attack",
           [hit(9), set_counter("guard_step", 1)],
           [(4, lambda: [hit(10), set_counter("guard_step", 1)])]),
    action("the_guardian.twin_slam", "Twin Slam", "Twin Slam - 8 damage x2", "Attack",
           [hit(8), hit(8), drop_status("standard.sharp_hide"), set_counter("guard_step", 2)]),

    # ---------------------------------------------------------------- Hexaghost
    action("hexaghost.activate", "Activate", "Activate - no effect", "Special", []),
    # "Deals (N+1)x6, N = Player's HP at the start of the turn, divided by 12 (rounded down)."
    # Both pieces exist -- `currentHealth` and `divide` -- and `node.repeat` takes an expression, so
    # this is the first content-side use of "run this move a computed number of times". The hero's
    # HP is read when the move resolves rather than at the start of the turn: one turn of drift,
    # and it is the only number in this file that depends on the player's state.
    action("hexaghost.divider", "Divider", "Divider - (HP/12 + 1) damage x6", "Attack",
           [repeat(add(divide(current_health(hero()), 12), const(1)), hit(6))]),
    action("hexaghost.sear", "Sear", "Sear - 6 damage, 1 Burn into your discard pile", "Attack",
           [hit(6), card_to_discard("burn", 1)],
           [(19, lambda: [hit(6), card_to_discard("burn", 2)])]),
    action("hexaghost.tackle", "Tackle", "Tackle - 5 damage x2", "Attack",
           [hit(5), hit(5)], [(4, lambda: [hit(6), hit(6)])]),
    action("hexaghost.inflame", "Inflame", "Inflame - 12 Block, 2 Strength", "Defend",
           [block(12), status("standard.strength", 2, "source")],
           [(19, lambda: [block(12), status("standard.strength", 3, "source")])]),
    action("hexaghost.inferno", "Inferno", "Inferno - 2 damage x6, 3 Burn+ into your discard pile",
           "Attack",
           [hit(2), hit(2), hit(2), hit(2), hit(2), hit(2), card_to_discard("burn+", 3)],
           [(4, lambda: [hit(3), hit(3), hit(3), hit(3), hit(3), hit(3),
                         card_to_discard("burn+", 3)])]),
]

# The 7-move pattern, **rotated** so that the default `(round - 1) % 7` lands on the wiki's order
# from turn 3 on (rounds 1 and 2 are the two opening rules below). Rotation, not reordering for
# taste:  L[2..6] + L[0..1] must read sear, tackle, sear, inflame, tackle, sear, inferno.
HEXAGHOST_CYCLE = ["hexaghost.sear", "hexaghost.inferno", "hexaghost.sear", "hexaghost.tackle",
                   "hexaghost.sear", "hexaghost.inflame", "hexaghost.tackle"]

GUARDIAN = dict(
    id="the_guardian",
    name="The Guardian",
    hp=240,
    actions=["the_guardian.charging_up", "the_guardian.fierce_bash",
             "the_guardian.vent_steam", "the_guardian.whirlwind"],
    starting=[],
    rules=[
        # Mode Shift, approximated: the wiki triggers it "after losing X HP" and swaps the *current*
        # intent; an intent here is chosen once per round, so the swap lands on the next round and
        # the trigger is the health threshold the player can see.
        rule(c_all([c_health("LessOrEqual", 50), c_counter("guard_mode", "LessOrEqual", 0)]),
             "the_guardian.defensive_mode", 80),
        rule(c_all([c_counter("guard_mode", "GreaterOrEqual", 1), c_counter("guard_step", "Equal", 0)]),
             "the_guardian.roll_attack", 70),
        rule(c_all([c_counter("guard_mode", "GreaterOrEqual", 1), c_counter("guard_step", "Equal", 1)]),
             "the_guardian.twin_slam", 70),
        rule(c_all([c_counter("guard_mode", "GreaterOrEqual", 1), c_counter("guard_step", "Equal", 2)]),
             "the_guardian.whirlwind", 70),
    ],
    note="§194：wiki 数值（HP 240/250；Fierce Bash 32→A4 36；Whirlwind 5×4；Roll Attack 9→A4 10；"
         "Twin Slam 8×2；Defensive Mode 20 Block + 3 Sharp Hide，A19 4）。"
         "⚠️ 偏差：Mode Shift 是『显示 HP ≤ 50% 时切一次』，且切换落在**下一轮**而不是当场改意图"
         "（本内核的意图是每轮选一次）；Sharp Hide 是精确的（`CardPlayed` + `card.hasTag.attack`）。",
)

HEXAGHOST = dict(
    id="hexaghost",
    name="Hexaghost",
    hp=250,
    actions=HEXAGHOST_CYCLE,
    starting=[],
    rules=[
        rule(c_round("Equal", 1), "hexaghost.activate", 60),
        rule(c_round("Equal", 2), "hexaghost.divider", 60),
    ],
    note="§194：wiki 数值（HP 250/264；Activate；Divider (HP/12+1)×6；Sear 6 + 1 Burn（A19 2）；"
         "Tackle 5×2→A4 6×2；Inflame 12 Block + 2 Str（A19 3）；Inferno 2×6→A4 3×6 + 3 Burn+）。"
         "⚠️ 偏差：Divider 读的是**结算时**的英雄 HP（wiki 是回合开始时）；Inferno 不升级已有 Burn。",
)
