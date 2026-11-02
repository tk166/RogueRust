"""§175: act 3's two missing elites -- Nemesis and Reptomancer -- plus the Dagger and the Burn card.

Wiki numbers (A0), quoted so they can be checked:

| enemy | HP | moves |
|---|---|---|
| Nemesis | 185 | Tri Attack 6×3; Tri Burn (3 Burn into discard); Scythe 45; **Intangible every other turn** |
| Reptomancer | 180-190 | Spawn Dagger (1); Big Bite 30; Snake Strike 13×2 + 1 Weak |
| Dagger | 20-25 | Wound 9 + 1 Wound into discard; Explode 25 (dies) |

Three mechanisms, all of which the kernel already has but this content had never used:

1. **A `TurnStarted` status trigger** -- no content row used that event before. It carries Nemesis's
   "intangible every other turn": the trigger reads its own counter (the effect queue has not applied
   this turn's bump yet, so it sees the *previous* tick), flips intangible on/off with a
   `node.conditional`, then bumps.
2. **`node.createCombatant`** -- the summon. Slime Boss's split uses it; this is the first *voluntary*
   summon. (The wiki's "up to a maximum of 4" is not expressible: the node has no cap, and
   `MAX_ENEMY_SLOTS` is the only bound. Recorded as a deviation.)
3. **`LifecyclePrograms[TurnEndInHand]`** -- Burn's "at the end of your turn, take 2 damage". The
   host has run card lifecycle programs since §1; 62/62 cards had an empty map, so nothing ever
   exercised it. Burn is the first card that does.

Deviations, stated rather than implied:

* **Dagger's Explode does not kill the Dagger.** The kernel has no `destroyCombatant` node (the
  opcode table has no such kind), so the damage lands and the dagger stays. This is the one place
  where the fight is measurably easier than the wiki's.
* **Reptomancer's summon has no cap** (see above) and the fight starts with two Daggers instead of
  one-at-a-time summoning from empty, because the encounter record cannot spawn mid-fight.
* **Nemesis's Intangible** goes on at the *second* turn start and alternates from there (the wiki says
  "every other turn" without saying which one comes first).

Run:  python D:\\Vibe\\sts-tui\\native\\patch_175_act3.py
Then: python tools/contentc/build.py --package sts
"""

import io
import json
import os

SRC = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "tools", "contentc", "packages", "sts", "sts.roguedeck.json",
)

with io.open(SRC, encoding="utf-8") as handle:
    document = json.load(handle)


def selector(kind, capability):
    return {"kind": kind,
            "value": {"Cardinality": "ZeroOrOne",
                      "RequiredContextCapabilities": capability}}


def source():
    return selector("sel.source", "Source")


def hero():
    return selector("sel.eventTarget", "EventTarget")


def program(children):
    return {
        "Id": {"Value": "(unnamed)"},
        "Root": {"kind": "node.sequence", "value": {"Children": children}}
        if len(children) != 1
        else children[0],
        "MaxNodeDepth": 64,
        "MaxProgramSteps": 1024,
    }


def const(value):
    return {"kind": "const", "value": {"Value": value}}


def remainder(left, right):
    return {"kind": "remainder", "value": {"Dividend": left, "Divisor": right}}


def status_stacks(status_id):
    return {
        "kind": "combatantStatusStacks",
        "value": {"Selector": source(), "StatusId": {"value": status_id}},
    }


def counter(name):
    return {"kind": "combatantCounter", "value": {"Selector": source(), "CounterId": name}}


def damage(amount):
    return {
        "kind": "node.dealDamage",
        "value": {
            "TargetSelector": hero(),
            "Amount": const(amount),
            "ResultKey": None,
            "IgnoresBlock": False,
            "Element": None,
        },
    }


def status(status_id, stacks, target="event"):
    return {
        "kind": "node.applyStatus",
        "value": {
            "TargetSelector": hero() if target == "event" else source(),
            "StatusDefinitionId": {"value": status_id},
            "Stacks": const(stacks),
            "DurationTurns": 0,
            "Charges": 0,
            "ResultKey": None,
        },
    }


def modify(status_id, delta, target="source"):
    return {
        "kind": "node.modifyStatusStacks",
        "value": {
            "TargetSelector": source() if target == "source" else hero(),
            "StatusDefinitionId": {"value": status_id},
            "Delta": const(delta),
        },
    }


def card_to_discard(card_id, count):
    return {
        "kind": "node.createCardInstance",
        "value": {
            "CardDefinitionId": {"value": card_id},
            "Count": const(count),
            "TargetSelector": hero(),
            "ToZone": "DiscardPile",
            "ResultKey": None,
        },
    }


def summon(definition, health):
    return {
        "kind": "node.createCombatant",
        "value": {
            "DefinitionId": definition,
            "TeamId": "enemy",
            "Health": const(health),
        },
    }


def conditional(condition, then, otherwise):
    return {
        "kind": "node.conditional",
        "value": {"Condition": condition, "Then": then, "Else": otherwise},
    }


def compare(op, left, right):
    return {"kind": "compare", "value": {"Op": op, "Left": left, "Right": right}}


def action(action_id, name, label, intent, children):
    return {
        "Id": action_id,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": label,
        "Intent": {"Kind": intent, "Label": label},
        "Program": program(children),
    }


# ---- actions --------------------------------------------------------------------------------
NEW_ACTIONS = [
    # Nemesis: 6×3, 3 Burns into the discard pile, 45.
    action("nemesis.tri_attack", "Tri Attack", "Tri Attack - 6 damage x3", "Attack",
           [damage(6), damage(6), damage(6)]),
    action("nemesis.tri_burn", "Tri Burn", "Tri Burn - 3 Burn into your discard pile", "Debuff",
           [card_to_discard("burn", 3)]),
    action("nemesis.scythe", "Scythe", "Scythe - 45 damage", "Attack", [damage(45)]),
    # Reptomancer: summon / 30 / 13×2 + 1 Weak.
    action("reptomancer.spawn_dagger", "Spawn Dagger", "Spawn Dagger - summons a Dagger", "Buff",
           [summon("dagger", 22)]),
    action("reptomancer.big_bite", "Big Bite", "Big Bite - 30 damage", "Attack", [damage(30)]),
    action("reptomancer.snake_strike", "Snake Strike", "Snake Strike - 13 damage x2, 1 Weak",
           "Attack", [damage(13), damage(13), status("standard.weak", 1)]),
    # Dagger: 9 + a Wound, then 25 and (in the wiki) it dies.
    action("dagger.wound", "Wound", "Wound - 9 damage, 1 Wound into your discard pile", "Attack",
           [damage(9), card_to_discard("wound", 1)]),
    action("dagger.explode", "Explode", "Explode - 25 damage", "Attack", [damage(25)]),
]

actions = document["EnemyActions"]
existing_actions = {record["Id"] for record in actions}
for record in NEW_ACTIONS:
    if record["Id"] not in existing_actions:
        actions.append(record)

# ---- the Burn card --------------------------------------------------------------------------
# "At the end of your turn, take 2 damage." That is `LifecyclePrograms.TurnEndInHand`, which the host
# has run since §1 and which no card had ever populated.
cards = document["Cards"]
if not any(card["Id"] == "burn" for card in cards):
    burn = json.loads(json.dumps(next(card for card in cards if card["Id"] == "wound")))
    burn["Id"] = "burn"
    burn["NameKey"] = "Burn"
    burn["DescriptionKey"] = "Unplayable. At the end of your turn, take 2 damage."
    burn["LifecyclePrograms"] = {
        "TurnEndInHand": program([
            {
                "kind": "node.dealDamage",
                "value": {
                    # `sel.source` in a card lifecycle program is the **card's holder**.
                    "TargetSelector": source(),
                    "Amount": const(2),
                    "ResultKey": None,
                    "IgnoresBlock": False,
                    "Element": None,
                },
            }
        ])
    }
    cards.append(burn)

# ---- the carrier status for Nemesis's alternating Intangible --------------------------------
# No content row had ever used a `TurnStarted` trigger. This one reads its own tick counter *before*
# this turn's bump is applied (effects are queued), so the parity it sees is the previous turn's.
statuses = document["Statuses"]
if not any(row["Id"] == "standard.phantom_veil" for row in statuses):
    # ⚠️ 用**"身上有没有无形"**来翻转，而不是 `remainder(tick, 2)`：`remainder` 在 `expr.rs` 里只有
    # 名字、**没有求值分支**（和 `divide` 一样是"参考有、内核未落地"），用它会让触发器求值即报错。
    # 翻转判据只用一条已实现的表达式 `combatantStatusStacks`，效果与"隔回合"完全等价。
    chain = [
        conditional(
            compare("Equal", status_stacks("standard.intangible"), const(0)),
            status("standard.intangible", 1, "source"),
            # Intangible 在内核里没有时长轴（`UsesDuration: false`），所以"没有的那一回合"必须显式摘掉；
            # -99 会被夹到 0 并删除实例。
            modify("standard.intangible", -99, "source"),
        ),
    ]
    statuses.append({
        "Id": "standard.phantom_veil",
        "PackageId": "sts",
        "NameKey": "Phantom Veil",
        "DescriptionKey": "Gains Intangible every other turn.",
        "Polarity": "Buff",
        "UsesStacks": False,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff"],
        "PassiveModifiers": [],
        "Triggers": [{"Event": "TurnStarted", "Program": program(chain)}],
    })

# ---- monsters -------------------------------------------------------------------------------
NEW_MONSTERS = [
    ("nemesis", "Nemesis", 185, 185, "Elite",
     ["nemesis.tri_attack", "nemesis.tri_burn", "nemesis.scythe"],
     [{"StatusDefinitionId": {"value": "standard.phantom_veil"}, "Stacks": 1}],
     [],
     "https://slaythespire.wiki.gg/wiki/Nemesis",
     "§175：wiki 数值（HP 185；Tri Attack 6×3；Tri Burn 3 张 Burn；Scythe 45；隔回合无形）。"
     "隔回合由 `standard.phantom_veil` 的 TurnStarted 触发器实现（读自己的 tick 奇偶）。"),
    ("reptomancer", "Reptomancer", 180, 190, "Elite",
     ["reptomancer.spawn_dagger", "reptomancer.big_bite", "reptomancer.snake_strike"],
     [], [],
     "https://slaythespire.wiki.gg/wiki/Reptomancer",
     "§175：wiki 数值（HP 180-190；Big Bite 30；Snake Strike 13×2 + 1 Weak；Spawn Dagger）。"
     "⚠️ 偏差：召唤没有『上限 4』（`node.createCombatant` 没有上限参数，唯一的界是 6 个敌人槽）。"),
    ("dagger", "Dagger", 20, 25, "Normal",
     ["dagger.wound", "dagger.explode"],
     [], [],
     "https://slaythespire.wiki.gg/wiki/Dagger",
     "§175：wiki 数值（HP 20-25；Wound 9 + 1 Wound；Explode 25 且**自身死亡**）。"
     "⚠️ 偏差：`Explode` 之后不自毁 —— 内核没有 `destroyCombatant` 这个节点。"),
]

monsters = document["Monsters"]
existing_monsters = {monster["Id"] for monster in monsters}
for monster_id, name, low, high, tier, action_ids, statuses_in, rules, inv, note in NEW_MONSTERS:
    if monster_id in existing_monsters:
        continue
    monsters.append({
        "Id": monster_id,
        "NameKey": name,
        "HpMin": low,
        "HpMax": high,
        "MaxHealth": low,
        "Actions": [{"value": action_id} for action_id in action_ids],
        "StartingStatuses": statuses_in,
        "IntentRules": rules,
        "Tier": tier,
        "InvRef": inv,
        "AiNote": note,
    })


def as_encounter_enemy(monster_id):
    record = next(m for m in monsters if m["Id"] == monster_id)
    return {
        "Id": record["Id"],
        "MaxHealth": record["MaxHealth"],
        "Actions": list(record["Actions"]),
        "StartingStatuses": list(record["StartingStatuses"]),
        "Position": 0,
        "IntentRules": list(record["IntentRules"]),
        "DisplayName": record["NameKey"],
    }


# The wiki's Reptomancer is found "with two other Daggers", so the encounter opens with them.
NEW_ENCOUNTERS = [
    ("enc_nemesis", [as_encounter_enemy("nemesis")]),
    ("enc_reptomancer", [as_encounter_enemy("reptomancer"),
                         as_encounter_enemy("dagger"),
                         as_encounter_enemy("dagger")]),
]

encounters = document["Encounters"]
existing_encounters = {encounter["Id"]["Value"] for encounter in encounters}
for name, enemies in NEW_ENCOUNTERS:
    if name in existing_encounters:
        continue
    encounters.append({
        "Id": {"Value": name},
        "Enemies": enemies,
        "HeroResources": [{"Resource": {"value": "standard.energy"}, "Current": 3, "Max": 3}],
        "HeroStartingStatuses": [],
        "TriggeredEffects": [],
        "HeroDisplayName": None,
        "CardsDrawnPerTurn": None,
    })

tables = document["EncounterTables"]
for encounter_id in ("enc_nemesis", "enc_reptomancer"):
    rows = tables.setdefault("Elite3", [])
    if not any(row["Id"] == encounter_id for row in rows):
        rows.append({"Id": encounter_id, "Weight": rows[0]["Weight"] if rows else 100})

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("elite pools:", {pool: [row["Id"] for row in tables[pool]]
                       for pool in ("Elite", "Elite2", "Elite3")})
