"""§194: align the boss pools with the wiki -- three bosses per act, wiki numbers.

What was there: one boss per act (`Boss` = Slime Boss, `Boss2` = The Champ, `Boss3` = Time Eater),
and the act-2/3 pair were **invented** (§130 said so: "不是 wiki 的数值照搬，而是机制上真的不同").
The wiki says each act picks **one of three** bosses.

Sources: `native/wiki_asc/<name>.txt` (fetched with `action=raw`, `native/fetch_wiki_bosses.py`).

| boss | act | HP | wiki | what this file does |
|---|---|---|---|---|
| Slime Boss | 1 | 140 | ✓ already faithful | — |
| The Guardian | 1 | 240 | new | 7 moves, Mode Shift by HP threshold |
| Hexaghost | 1 | 250 | new | 7-move pattern + Divider as `repeat(HP/12+1)` |
| The Champ | 2 | **420** (was 330 invented) | realign | +Face Slap/Gloat/Taunt/Anger, Metallicize 5 |
| Bronze Automaton | 2 | 300 | new | 6-cycle + 2 orbs, A19 Stunned->Boost |
| The Collector | 2 | 282 | new | Fireball/Buff + turn-4 Mega Debuff + 2 Torch Heads |
| Time Eater | 3 | 456 | realign | +Haste, A4/A19 variants |
| Awakened One | 3 | 300 | new | two phases through counters |
| Donu / Deca | 3 | 250 each | new | a **pair** (the first two-enemy boss) |

Deviations (mechanism gaps, stated rather than implied -- each one also lives in the monster's
`AiNote`, which is what the next reader will actually see):

1. **A9 `AscHP` is not the wiki's number.** The run layer multiplies `MaxHealth` by a percent
   (§159's A7/A8/A9 rule), so The Champ shows 420 and A9 gives 525, not the wiki's 440. The *base*
   HP is the wiki's now; the A9 shortcut predates this section.
2. **Minions are deployed at fight start, not summoned.** `intent::locate_enemy` resolves a summoned
   combatant's move set through an encounter roster (§138), so the fight that lists them is what
   makes them act -- and listing them spawns them. Bronze Orbs (2) and Torch Heads (2) therefore
   start on the field; the wiki's "Spawn Orbs" / "Spawn" moves are dropped.
3. **No `Stasis`** (Bronze Orb steals a card and gives it back on death): no card-stealing primitive.
4. **The Guardian's Mode Shift** is HP-threshold driven, once, and lands on the *next* round (an
   intent is chosen per round here). `Sharp Hide` is exact.
5. **Awakened One's Rebirth** fires at <= 25% HP instead of at 0 (no death interceptor); "removes all
   Debuffs" drops Curiosity by name; the Cultists are absent.
6. **Time Eater's Haste** heals to 50% (no debuff clear); `Draw Reduction` is not modelled.
7. **The Champ's Anger** clears Weak/Vulnerable/Frail by name; the A19 Gloat swap is not modelled.
8. **The Collector's** 25/45/30 weighting is a deterministic cycle; `Spawn` is dropped (see 2).
9. **Donu/Deca's Artifact 2** does not become 3 at A19 (`StartingStatuses` has no ascension axis).

Run:  python native/patch_194_bosses.py
Then: python tools/contentc/build.py --package sts
"""

import io
import json
import sys

sys.path.insert(0, "native")

from p194_act1 import ACTIONS as ACT1_ACTIONS, GUARDIAN, HEXAGHOST  # noqa: E402
from p194_act2 import ACTIONS as ACT2_ACTIONS, AUTOMATON, ORB, COLLECTOR, TORCH_HEAD  # noqa: E402
from p194_act3 import ACTIONS as ACT3_ACTIONS, AWAKENED_ONE, DONU, DECA  # noqa: E402
from p194_helpers import (  # noqa: E402
    action, block, c_all, c_counter, c_health, c_rounds, card_to_discard, drop_status, hero, hit,
    rule, set_counter, status,
)

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
actions = document["EnemyActions"]
monsters = document["Monsters"]
statuses = document["Statuses"]
cards = document["Cards"]
encounters = document["Encounters"]
tables = document["EncounterTables"]

by_action = {record["Id"]: record for record in actions}
by_monster = {record["Id"]: record for record in monsters}

# ===========================================================================
# 1. two statuses the new bosses need
# ===========================================================================

if "standard.sharp_hide" not in {row["Id"] for row in statuses}:
    statuses.append({
        "Id": "standard.sharp_hide",
        "PackageId": "sts",
        "NameKey": "Sharp Hide",
        "DescriptionKey": "Whenever you play an Attack, take X damage.",
        "Polarity": "Buff",
        "UsesStacks": True,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff", "sharp_hide"],
        "PassiveModifiers": [],
        # The same shape as `standard.enrage` (the only `CardPlayed` condition this kernel reads:
        # `event.bool` + `FieldKey: card.hasTag.<tag>`), with "damage the card player" instead of
        # "gain Strength". `sel.eventTarget` is the player: `run_card_played_triggers` passes the
        # card's owner as the event target and the bearer (the Guardian) as the source.
        "Triggers": [{
            "Event": "CardPlayed",
            "Program": {
                "Id": {"Value": "(unnamed)"},
                "Root": {
                    "kind": "node.conditional",
                    "value": {
                        "Condition": {"kind": "event.bool",
                                      "value": {"FieldKey": "card.hasTag.attack"}},
                        "Then": hit({
                            "kind": "combatantStatusStacks",
                            "value": {"Selector": {"kind": "sel.source",
                                                   "value": {"Cardinality": "ZeroOrOne",
                                                             "RequiredContextCapabilities": "Source"}},
                                      "StatusId": {"value": "standard.sharp_hide"}},
                        }, hero()),
                        "Else": None,
                    },
                },
                "MaxNodeDepth": 64,
                "MaxProgramSteps": 1024,
            },
        }],
    })

if "standard.curiosity" not in {row["Id"] for row in statuses}:
    statuses.append({
        "Id": "standard.curiosity",
        "PackageId": "sts",
        "NameKey": "Curiosity",
        "DescriptionKey": "Whenever you play a Power card, gains X Strength.",
        "Polarity": "Buff",
        "UsesStacks": True,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff", "curiosity"],
        "PassiveModifiers": [],
        "Triggers": [{
            "Event": "CardPlayed",
            "Program": {
                "Id": {"Value": "(unnamed)"},
                "Root": {
                    "kind": "node.conditional",
                    "value": {
                        "Condition": {"kind": "event.bool",
                                      "value": {"FieldKey": "card.hasTag.power"}},
                        "Then": status("standard.strength", {
                            "kind": "combatantStatusStacks",
                            "value": {"Selector": {"kind": "sel.source",
                                                   "value": {"Cardinality": "ZeroOrOne",
                                                             "RequiredContextCapabilities": "Source"}},
                                      "StatusId": {"value": "standard.curiosity"}},
                        }, "source"),
                        "Else": None,
                    },
                },
                "MaxNodeDepth": 64,
                "MaxProgramSteps": 1024,
            },
        }],
    })

# ===========================================================================
# 2. two cards: `burn+` (Hexaghost's Inferno) and `void` (Awakened One's Sludge)
# ===========================================================================

if "burn+" not in {row["Id"] for row in cards}:
    upgraded = json.loads(json.dumps(next(row for row in cards if row["Id"] == "burn")))
    upgraded["Id"] = "burn+"
    upgraded["NameKey"] = "Burn+"
    upgraded["DescriptionKey"] = "Unplayable. At the end of your turn, take 4 damage."
    upgraded["LifecyclePrograms"]["TurnEndInHand"]["Root"]["value"]["Amount"]["value"]["Value"] = 4
    cards.append(upgraded)

if "void" not in {row["Id"] for row in cards}:
    void = json.loads(json.dumps(next(row for row in cards if row["Id"] == "dazed")))
    void["Id"] = "void"
    void["NameKey"] = "Void"
    # The wiki's Void also says "whenever this card is drawn, lose 1 Energy". Nothing in this
    # content vocabulary can say "the card that just moved is *this* card", so that half is absent
    # and the text says only what happens.
    void["DescriptionKey"] = "Unplayable. Ethereal."
    void["Tags"] = [{"value": "status"}, {"value": "unplayable"}, {"value": "ethereal"},
                    {"value": "junk"}]
    cards.append(void)

# ===========================================================================
# 3. the three new-actions batches
# ===========================================================================

added_actions = 0
for record in ACT1_ACTIONS + ACT2_ACTIONS + ACT3_ACTIONS:
    if record["Id"] in by_action:
        raise SystemExit("action already present: " + record["Id"])
    actions.append(record)
    added_actions += 1

# ===========================================================================
# 4. realign the two invented bosses (The Champ, Time Eater)
# ===========================================================================

# --- The Champ: 420 HP (the wiki's), Face Slap / Gloat / Taunt / Anger, Metallicize 5.
CHAMP_NEW = [
    action("the_champ.face_slap", "Face Slap", "Face Slap - 12 damage, 2 Frail, 2 Vulnerable", "Attack",
           [hit(12), status("standard.frail", 2), status("standard.vulnerable", 2)],
           [(4, lambda: [hit(14), status("standard.frail", 2), status("standard.vulnerable", 2)])]),
    action("the_champ.gloat", "Gloat", "Gloat - 2 Strength", "Buff",
           [status("standard.strength", 2, "source")],
           [(4, lambda: [status("standard.strength", 3, "source")]),
            (19, lambda: [status("standard.strength", 4, "source")])]),
    action("the_champ.taunt", "Taunt", "Taunt - 2 Weak, 2 Vulnerable", "Debuff",
           [status("standard.weak", 2), status("standard.vulnerable", 2)]),
    # "Removes all Debuffs. Gains 6 Strength (A4 9, A19 12)." There is no "clear all" node, so the
    # three debuffs this content can put on an enemy are dropped by name.
    action("the_champ.anger", "Anger", "Anger - clears debuffs, 6 Strength", "Buff",
           [drop_status("standard.weak"), drop_status("standard.vulnerable"),
            drop_status("standard.frail"), status("standard.strength", 6, "source"),
            set_counter("champ_phase", 1), set_counter("champ_exec", 0)],
           [(4, lambda: [drop_status("standard.weak"), drop_status("standard.vulnerable"),
                         drop_status("standard.frail"), status("standard.strength", 9, "source"),
                         set_counter("champ_phase", 1), set_counter("champ_exec", 0)]),
            (19, lambda: [drop_status("standard.weak"), drop_status("standard.vulnerable"),
                          drop_status("standard.frail"), status("standard.strength", 12, "source"),
                          set_counter("champ_phase", 1), set_counter("champ_exec", 0)])]),
]
for record in CHAMP_NEW:
    if record["Id"] not in by_action:
        actions.append(record)
        added_actions += 1

# The old Defensive Stance had Metallicize 2 (invented). The wiki says 5 -> A9 6 -> A19 7, with
# Block 15 -> 18 -> 20. The base program is rewritten and the variants replaced.
champ_stance = by_action["the_champ.defensive_stance"]
champ_stance["Program"] = {
    "Id": {"Value": "(unnamed)"},
    "Root": {"kind": "node.sequence", "value": {"Children": [
        block(15), status("standard.metallicize", 5, "source")]}},
    "MaxNodeDepth": 64, "MaxProgramSteps": 1024,
}
champ_stance["ProgramAsc"] = [
    {"AscensionMin": 9, "Program": {
        "Id": {"Value": "(unnamed)"},
        "Root": {"kind": "node.sequence", "value": {"Children": [
            block(18), status("standard.metallicize", 6, "source")]}},
        "MaxNodeDepth": 64, "MaxProgramSteps": 1024}},
    {"AscensionMin": 19, "Program": {
        "Id": {"Value": "(unnamed)"},
        "Root": {"kind": "node.sequence", "value": {"Children": [
            block(20), status("standard.metallicize", 7, "source")]}},
        "MaxNodeDepth": 64, "MaxProgramSteps": 1024}},
]

# Heavy Slash's label still said "18 damage" from before §191 moved the base to 16.
by_action["the_champ.heavy_slash"]["Intent"]["Label"] = "Heavy Slash - 16 damage"
by_action["the_champ.heavy_slash"]["DescriptionKey"] = "Heavy Slash - 16 damage"

# --- Time Eater: Haste, plus the A4/A19 halves the page states.
time_new = [
    action("time_eater.haste", "Haste", "Haste - heals to half HP", "Buff",
           [{"kind": "node.heal",
             "value": {"TargetSelector": {"kind": "sel.source",
                                          "value": {"Cardinality": "ZeroOrOne",
                                                    "RequiredContextCapabilities": "Source"}},
                       "Amount": {"kind": "max", "value": {
                           "Left": {"kind": "subtract", "value": {
                               "Left": {"kind": "divide", "value": {
                                   "Left": {"kind": "maxHealth", "value": {"Selector": {
                                       "kind": "sel.source",
                                       "value": {"Cardinality": "ZeroOrOne",
                                                 "RequiredContextCapabilities": "Source"}}}},
                                   "Right": {"kind": "const", "value": {"Value": 2}}}},
                               "Right": {"kind": "currentHealth", "value": {"Selector": {
                                   "kind": "sel.source",
                                   "value": {"Cardinality": "ZeroOrOne",
                                             "RequiredContextCapabilities": "Source"}}}}}},
                           "Right": {"kind": "const", "value": {"Value": 0}}}},
                       "ResultKey": None}},
            set_counter("te_haste", 1)],
           [(19, lambda: [{"kind": "node.heal",
                           "value": {"TargetSelector": {"kind": "sel.source",
                                                        "value": {"Cardinality": "ZeroOrOne",
                                                                  "RequiredContextCapabilities": "Source"}},
                                     "Amount": {"kind": "max", "value": {
                                         "Left": {"kind": "subtract", "value": {
                                             "Left": {"kind": "divide", "value": {
                                                 "Left": {"kind": "maxHealth", "value": {"Selector": {
                                                     "kind": "sel.source",
                                                     "value": {"Cardinality": "ZeroOrOne",
                                                               "RequiredContextCapabilities": "Source"}}}},
                                                 "Right": {"kind": "const", "value": {"Value": 2}}}},
                                             "Right": {"kind": "currentHealth", "value": {"Selector": {
                                                 "kind": "sel.source",
                                                 "value": {"Cardinality": "ZeroOrOne",
                                                           "RequiredContextCapabilities": "Source"}}}}}},
                                         "Right": {"kind": "const", "value": {"Value": 0}}}},
                                     "ResultKey": None}},
                          block(32), set_counter("te_haste", 1)])]),
]
for record in time_new:
    if record["Id"] not in by_action:
        actions.append(record)
        added_actions += 1

# Reverberate 7x3 -> A4 8x3; Head Slam +2 Slimed at A19; Ripple +1 Frail at A19.
by_action["time_eater.reverberate"]["ProgramAsc"] = [{
    "AscensionMin": 4,
    "Program": {"Id": {"Value": "(unnamed)"},
                "Root": {"kind": "node.sequence", "value": {"Children": [hit(8), hit(8), hit(8)]}},
                "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
}]
by_action["time_eater.head_slam"]["ProgramAsc"] = [{
    "AscensionMin": 19,
    "Program": {"Id": {"Value": "(unnamed)"},
                "Root": {"kind": "node.sequence", "value": {"Children": [
                    hit(26), card_to_discard("slimed", 2)]}},
                "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
}]
by_action["time_eater.ripple"]["ProgramAsc"] = [{
    "AscensionMin": 19,
    "Program": {"Id": {"Value": "(unnamed)"},
                "Root": {"kind": "node.sequence", "value": {"Children": [
                    block(20), status("standard.weak", 1), status("standard.vulnerable", 1),
                    status("standard.frail", 1)]}},
                "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
}]

# ===========================================================================
# 5. the roster: new monsters + the two realignments
# ===========================================================================


def roster_entry(spec, tier="Boss"):
    return {
        "Id": spec["id"],
        "NameKey": spec["name"],
        "HpMin": spec["hp"],
        "HpMax": spec["hp"],
        "MaxHealth": spec["hp"],
        "Actions": [{"value": action_id} for action_id in spec["actions"]],
        "StartingStatuses": spec["starting"],
        "IntentRules": spec["rules"],
        "Tier": tier,
        "InvRef": "https://slaythespire.wiki.gg/wiki/" + spec["name"].replace(" ", "_"),
        "AiNote": spec["note"],
    }


for spec, tier in ((GUARDIAN, "Boss"), (HEXAGHOST, "Boss"), (AUTOMATON, "Boss"),
                   (ORB, "Normal"), (COLLECTOR, "Boss"), (TORCH_HEAD, "Normal"),
                   (AWAKENED_ONE, "Boss"), (DONU, "Boss"), (DECA, "Boss")):
    if spec["id"] in by_monster:
        raise SystemExit("monster already present: " + spec["id"])
    monsters.append(roster_entry(spec, tier))

# The Champ: 330 (invented) -> 420 (wiki). Actions gain the four new moves and the rule set.
champ = by_monster["the_champ"]
champ["HpMin"] = champ["HpMax"] = champ["MaxHealth"] = 420
champ["Actions"] = [{"value": name} for name in (
    "the_champ.heavy_slash", "the_champ.face_slap", "the_champ.defensive_stance",
    "the_champ.gloat")]
champ["IntentRules"] = [
    # Phase two: below half HP the next intent is Anger, then Execute, then the cycle resumes
    # (`champ_phase` / `champ_exec` are the two counters Anger and Execute set).
    rule(c_all([c_health("LessOrEqual", 50), c_counter("champ_phase", "LessOrEqual", 0)]),
         "the_champ.anger", 90),
    rule(c_all([c_counter("champ_phase", "GreaterOrEqual", 1),
                c_counter("champ_exec", "LessOrEqual", 0)]), "the_champ.execute", 85),
    # Taunt every 4 turns (rounds 4, 8, 12, ...): `anyOf` of concrete rounds stands in for a modulo.
    rule(c_rounds([4, 8, 12, 16, 20, 24]), "the_champ.taunt", 60),
]
champ["InvRef"] = "https://slaythespire.wiki.gg/wiki/The_Champ"
champ["AiNote"] = (
    "§194：wiki 数值（HP 420/440；Heavy Slash 16→A4 18；Face Slap 12→A4 14 + 2 Frail + 2 Vuln；"
    "Defensive Stance 15 Block + 5 Metallicize，A9 18/6、A19 20/7；Gloat 2 Str，A4 3、A19 4；"
    "Taunt 每 4 回合 2 Weak + 2 Vuln；Anger 清 debuff + 6 Str，A4 9、A19 12；Execute 10×2）。"
    "⚠️ 偏差：① 45/25/15/15 权重变成确定性 4 循环；② Anger 按名清掉 Weak/Vulnerable/Frail"
    "（没有『清空状态』节点）；③ A19 的『Gloat 换成 Defensive Stance』未实现。")

time_eater = by_monster["time_eater"]
time_eater["IntentRules"] = [
    rule(c_all([c_health("LessOrEqual", 50), c_counter("te_haste", "LessOrEqual", 0)]),
         "time_eater.haste", 90),
]
time_eater["InvRef"] = "https://slaythespire.wiki.gg/wiki/Time_Eater"
time_eater["AiNote"] = (
    "§194：wiki 数值（HP 456/480；Reverberate 7×3→A4 8×3；Head Slam 26→A4 32，A19 另加 2 Slimed；"
    "Ripple 20 Block + Weak + Vuln，A19 加 Frail；Haste 半血以下回满一半，A19 另给 32 Block）。"
    "⚠️ 偏差：① Haste 只回血（不清 debuff，没有『清空状态』节点）；② `Draw Reduction` 未实现"
    "（没有减少抽牌数的 debuff）；③ 45/35/20 权重变成确定性 3 循环。")

# ===========================================================================
# 6. encounters + pools
# ===========================================================================

# The two encounters that already exist carry an **inline copy** of the roster record (that is the
# shape `check_relations` compares: "Encounter.X/enemy: Actions differs from the roster's copy"), so
# realigning the roster is only half the job -- the copies have to be re-synced or the fight keeps
# the old numbers. This is exactly how "I changed the roster" turns into "the game still spawns the
# old boss" if nobody looks.
for existing in encounters:
    if existing["Id"]["Value"] not in ("enc_the_champ", "enc_time_eater"):
        continue
    for slot, enemy in enumerate(existing["Enemies"]):
        roster = next((row for row in monsters if row["Id"] == enemy["Id"]), None)
        assert roster is not None, enemy["Id"]
        existing["Enemies"][slot] = {
            "Id": roster["Id"],
            "MaxHealth": roster["MaxHealth"],
            "Actions": list(roster["Actions"]),
            "StartingStatuses": list(roster["StartingStatuses"]),
            "Position": None,
            "IntentRules": list(roster["IntentRules"]),
            "DisplayName": roster["NameKey"],
            "Rolls": [],
        }


def encounter_enemy(monster_id):
    record = next(row for row in monsters if row["Id"] == monster_id)
    return {
        "Id": record["Id"],
        "MaxHealth": record["MaxHealth"],
        "Actions": list(record["Actions"]),
        "StartingStatuses": list(record["StartingStatuses"]),
        "Position": None,
        "IntentRules": list(record["IntentRules"]),
        "DisplayName": record["NameKey"],
        "Rolls": [],
    }


NEW_ENCOUNTERS = [
    ("enc_the_guardian", ["the_guardian"]),
    ("enc_hexaghost", ["hexaghost"]),
    # The orbs start deployed (deviation 2): listing them is what lets them act at all.
    ("enc_bronze_automaton", ["bronze_automaton", "bronze_orb", "bronze_orb"]),
    ("enc_the_collector", ["the_collector", "torch_head", "torch_head"]),
    ("enc_awakened_one", ["awakened_one"]),
    ("enc_donu_and_deca", ["donu", "deca"]),
]

existing_encounters = {row["Id"]["Value"] for row in encounters}
for name, enemy_ids in NEW_ENCOUNTERS:
    if name in existing_encounters:
        raise SystemExit("encounter already present: " + name)
    encounters.append({
        "Id": {"Value": name},
        "Enemies": [encounter_enemy(enemy_id) for enemy_id in enemy_ids],
        # Same shape as every other encounter: `Resource` (wrapped lower), and the two display
        # fields left null so the kernel's default applies rather than a second copy of "5".
        "HeroResources": [{"Resource": {"value": "standard.energy"}, "Current": 3, "Max": 3}],
        "HeroStartingStatuses": [],
        "TriggeredEffects": [],
        "HeroDisplayName": None,
        "CardsDrawnPerTurn": None,
    })

# Three per act, equal weight (the wiki: "one of three, at random").
tables["Boss"] = [{"Id": name, "Weight": 100} for name in
                  ("enc_slime_boss", "enc_the_guardian", "enc_hexaghost")]
tables["Boss2"] = [{"Id": name, "Weight": 100} for name in
                   ("enc_the_champ", "enc_bronze_automaton", "enc_the_collector")]
tables["Boss3"] = [{"Id": name, "Weight": 100} for name in
                   ("enc_time_eater", "enc_awakened_one", "enc_donu_and_deca")]
tables["Note"] = (
    "§194：三幕的 Boss 池各自补齐到 wiki 的『三选一』（Boss = Slime Boss / The Guardian / Hexaghost；"
    "Boss2 = The Champ / Bronze Automaton / The Collector；Boss3 = Time Eater / Awakened One / "
    "Donu & Deca）。A20 的两场 Boss 因此可以是不同的一对。")

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("actions added: %d (total %d)" % (added_actions, len(actions)))
print("monsters: %d, statuses: %d, cards: %d, encounters: %d"
      % (len(monsters), len(statuses), len(cards), len(encounters)))
for key in ("Boss", "Boss2", "Boss3"):
    print("  %-6s %s" % (key, [row["Id"] for row in tables[key]]))
