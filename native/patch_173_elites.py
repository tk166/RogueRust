"""§173: the elite pool, aligned with the wiki -- act 1 and act 2 up to three each.

What the gap list said (`docs/sts-wiki-gap.md` §D): "精英池只有 4 个遭遇". The wiki's act 1 elites are
Gremlin Nob / Lagavulin / 3 Sentries; act 2's are Gremlin Leader / Slavers / Book of Stabbing. We had
nob + sentries (act 1, so **missing Lagavulin**) and gremlin_leader (act 2, **missing Slavers and Book
of Stabbing**). This patch adds those three, and nothing else.

Every number is from the wiki page, quoted in the table below. Everything uses mechanics the kernel
already has -- no new subsystem:

| elite | HP | moves (A0) | mechanics used |
|---|---|---|---|
| Lagavulin | 109-111 | Metallicize 8; Sleep ×3 (does nothing); Attack 18; Siphon Soul (-1 Str, -1 Dex) | starting status, `intent.round` rule |
| Book of Stabbing | 160-164 | Multi Stab 6×N (N = uses + 2); Big Stab 21 | counter + `node.repeat` |
| Taskmaster | 54-60 | Scouring Whip 7 + 1 Wound to discard | `node.createCardInstance` |

Plus one card the two of them need: **Wound** (unplayable, does nothing), copied from `slimed` -- the
status-card shape the kernel already reads.

Deviations, stated rather than implied:

* **Lagavulin**: the wiki's "if it takes any damage it is stunned for one turn, then attacks" needs an
  on-damaged trigger with a *stun*; here sleep is purely round-based (rounds 1-3), and the starting
  **Block 8** is not applied because nothing expresses "start with block" (Metallicize 8 is). Both are
  recorded in the monster's `AiNote`.
* **Book of Stabbing**: the wiki's "85% Multi Stab / 15% Big Stab, never 3× or 2× in a row" is a
  weighted pick with a history constraint. The chooser here is deterministic round-cycling, so the
  pattern alternates -- and the escalating `N` (which is what makes the fight) is exact.
* **Taskmaster** has one move, so the cycle is trivially that move.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_173_elites.py
Then: python tools/contentc/compile.py
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


def add(left, right):
    return {"kind": "add", "value": {"Left": left, "Right": right}}


def counter(name):
    return {"kind": "combatantCounter",
            "value": {"Selector": selector("sel.source", "Source"), "CounterId": name}}


def multiply(left, right):
    return {"kind": "multiply", "value": {"Left": left, "Right": right}}


def damage_expr(amount_expr, target="event"):
    node = damage(0, target)
    node["value"]["Amount"] = amount_expr
    return node


def damage(amount, target="event"):
    return {
        "kind": "node.dealDamage",
        "value": {
            "TargetSelector": selector("sel.eventTarget",
                                       "EventTarget" if target == "event" else "Source"),
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
            "TargetSelector": selector("sel.eventTarget",
                                       "EventTarget" if target == "event" else "Source"),
            "StatusDefinitionId": {"value": status_id},
            "Stacks": const(stacks),
            "DurationTurns": 0,
            "Charges": 0,
            "ResultKey": None,
        },
    }


def modify(status_id, delta):
    """`node.modifyStatusStacks`: add `delta` stacks (negative to take them away)."""
    return {
        "kind": "node.modifyStatusStacks",
        "value": {
            "TargetSelector": selector("sel.eventTarget", "EventTarget"),
            "StatusDefinitionId": {"value": status_id},
            "Delta": const(delta),
        },
    }


def counter_bump(name):
    """`counter = counter + 1`, written as an absolute `setCombatantCounter`.

    `fx.incrementCounter` exists in the content's opcode table but the kernel has **no dispatch** for
    it (grep: one hit, in `ir.rs`'s inventory list). `node.setCombatantCounter` *is* implemented and has
    an e2e test for exactly this shape (`exec.rs` §W4e: `min(add(combatantCounter{…}, 1), 3)`), so the
    increment is spelled as read-add-write.
    """
    return {
        "kind": "node.setCombatantCounter",
        "value": {
            "TargetSelector": selector("sel.source", "Source"),
            # ⚠️ **node** 里的 `CounterId` 是 `{"value": …}`（与 `StatusDefinitionId` 同一个方言），
            # 而这个文件里 `combatantCounter` **表达式**的 `CounterId` 是裸字符串。写成裸字符串会
            # 让编码错位、后面的 term 全部移位 —— 表现为一条**无关的** status 触发器读到非 term。
            "CounterId": {"value": name},
            # `Relative: true` + a constant is the shape the shipped content uses
            # (`standard.time_warp`): "add 1". Reading the old value inside the *write* was the part
            # that did not work in an enemy action -- see the module docstring of this section.
            "Amount": const(1),
            "Relative": True,
        },
    }


def repeat(count_expr, body, max_count=32):
    return {"kind": "node.repeat",
            "value": {"Count": count_expr, "Body": body, "MaxCount": max_count}}


def card_to_discard(card_id, count):
    return {
        "kind": "node.createCardInstance",
        "value": {
            "CardDefinitionId": {"value": card_id},
            "Count": const(count),
            "TargetSelector": selector("sel.eventTarget", "EventTarget"),
            "ToZone": "DiscardPile",
            "ResultKey": None,
        },
    }


def action(action_id, name, label, intent, children):
    return {
        "Id": action_id,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": label,
        "Intent": {"Kind": intent, "Label": label},
        "Program": program(children),
    }


def starting(status_id, stacks):
    return {"StatusDefinitionId": {"value": status_id}, "Stacks": stacks}


NEW_ACTIONS = [
    # ---- Lagavulin (act 1 elite) ------------------------------------------------------------
    # "Sleep: Does nothing." An empty program is the honest encoding: the turn is taken, nothing
    # happens. (The wiki's Stunned variant needs an on-damaged trigger; see the module docstring.)
    action("lagavulin.sleep", "Sleep", "Sleep - does nothing", "Unknown",
           [{"kind": "node.sequence", "value": {"Children": []}}]),
    action("lagavulin.attack", "Attack", "Attack - 18 damage", "Attack", [damage(18)]),
    # ⚠️ **不能**用 `applyStatus` 传负层数：那会让程序抛 `Exec`，而驱动把抛出记成 `StepThrew`
    # 之后局面停在"轮到敌人但它的回合没开始" —— §174 的死锁就是这么来的。
    # 减层数用 `modifyStatusStacks`（Delta 为负）。
    action("lagavulin.siphon_soul", "Siphon Soul", "Siphon Soul - -1 Strength, -1 Dexterity",
           "Debuff", [modify("standard.strength", -1), modify("standard.dexterity", -1)]),
    # ---- Book of Stabbing (act 2 elite) -----------------------------------------------------
    # "Deals 6×N damage. N = number of times Multi Stab was used this combat, plus 2."
    # After the bump `uses` is 1 on the first use, so N = uses + 2 = 3 → 18 damage, exactly the wiki.
    action("book_of_stabbing.multi_stab", "Multi Stab", "Multi Stab - 6 x (uses + 2) damage",
           "Attack",
           [# 伤害先算、递增后排：`setCombatantCounter` 是**入队的效果**，所以同一个程序里"写完立刻读"
            # 读到的是旧值（实测：先 bump 再 repeat，Count 仍是 2）。wiki 的 N = 本次战斗使用次数 + 2，
            # 而"已完成的次数 + 3"与它恒等（第一次 0+3=3、第二次 1+3=4…），所以读旧值正好是对的。
            repeat(add(counter("book_stab_uses"), const(3)), damage(6)),
            counter_bump("book_stab_uses")]),
    action("book_of_stabbing.big_stab", "Big Stab", "Big Stab - 21 damage", "Attack",
           [damage(21)]),
    # ---- Taskmaster (act 2 elite, with the two slavers) -------------------------------------
    action("taskmaster.scouring_whip", "Scouring Whip",
           "Scouring Whip - 7 damage, 1 Wound to discard", "Attack",
           [damage(7), card_to_discard("wound", 1)]),
]

actions = document["EnemyActions"]
existing_actions = {record["Id"] for record in actions}
for record in NEW_ACTIONS:
    if record["Id"] not in existing_actions:
        actions.append(record)

# ---- the Wound card (Taskmaster's and Dagger's payload) ------------------------------------
# Copied from `slimed` -- the same "status card, unplayable, does nothing" shape. It is what makes the
# discard pile matter, which is the point of both enemies.
cards = document["Cards"]
if not any(card["Id"] == "wound" for card in cards):
    wound = json.loads(json.dumps(next(card for card in cards if card["Id"] == "slimed")))
    wound["Id"] = "wound"
    wound["NameKey"] = "Wound"
    wound["DescriptionKey"] = "Unplayable."
    cards.append(wound)

NEW_MONSTERS = [
    ("lagavulin", "Lagavulin", 109, 111, "Elite",
     ["lagavulin.siphon_soul", "lagavulin.attack"],
     [starting("standard.metallicize", 8)],
     [{"Condition": {"kind": "intent.round",
                     "value": {"Op": "LessOrEqual", "Round": 3}},
       "Action": {"value": "lagavulin.sleep"},
       "Priority": 10}],
     "https://slaythespire.wiki.gg/wiki/Lagavulin",
     "§173：wiki 数值（HP 109-111、Metallicize 8、Attack 18、Siphon Soul -1 力量/-1 敏捷）。"
     "⚠️ 偏差：睡眠只按回合数（1-3）判定；wiki 的『受到伤害即惊醒并眩晕一回合』需要"
     "on-damaged 触发器 + stun，内核没有；起始 Block 8 也没表达（只有 Metallicize）。"
     "Actions 刻意排成 [siphon_soul, attack]，使第 4 回合（(4-1)%2=1）正好是 Attack —— "
     "wiki 说它醒来立刻攻击。"),
    ("book_of_stabbing", "Book of Stabbing", 160, 164, "Elite",
     ["book_of_stabbing.multi_stab", "book_of_stabbing.big_stab"],
     [],
     [],
     "https://slaythespire.wiki.gg/wiki/Book_of_Stabbing",
     "§173：wiki 数值（HP 160-164、Multi Stab 6×N、N=使用次数+2、Big Stab 21）。"
     "⚠️ 偏差：wiki 是 85%/15% 加权 + 『不能连续三次/两次』；本内核的挑招是确定性轮转，"
     "所以它是交替的。递增的 N 是精确的（计数器 + node.repeat）。"),
    ("taskmaster", "Taskmaster", 54, 60, "Elite",
     ["taskmaster.scouring_whip"],
     [],
     [],
     "https://slaythespire.wiki.gg/wiki/Taskmaster",
     "§173：wiki 数值（HP 54-60、Scouring Whip 7 伤害 + 1 张 Wound 进弃牌堆）。"
     "只有一个招式，所以轮转就是它。"),
]

monsters = document["Monsters"]
existing_monsters = {monster["Id"] for monster in monsters}
NEW_MONSTER_IDS = set()
for monster_id, name, low, high, tier, action_ids, statuses, rules, inv, note in NEW_MONSTERS:
    NEW_MONSTER_IDS.add(monster_id)
    if monster_id in existing_monsters:
        continue
    monsters.append({
        "Id": monster_id,
        "NameKey": name,
        "HpMin": low,
        "HpMax": high,
        "MaxHealth": low,
        "Actions": [{"value": action_id} for action_id in action_ids],
        "StartingStatuses": statuses,
        "IntentRules": rules,
        "Tier": tier,
        "InvRef": inv,
        "AiNote": note,
    })


def encounter_enemy(monster_id, display, health, action_ids, statuses=(), rules=()):
    return {
        "Id": monster_id,
        "MaxHealth": health,
        "Actions": [{"value": action_id} for action_id in action_ids],
        "StartingStatuses": list(statuses),
        "Position": 0,
        "IntentRules": list(rules),
        "DisplayName": display,
    }


def monster_of(monster_id):
    return next(m for m in monsters if m["Id"] == monster_id)


def as_encounter_enemy(monster_id):
    record = monster_of(monster_id)
    return encounter_enemy(record["Id"], record["NameKey"], record["MaxHealth"],
                           [entry["value"] for entry in record["Actions"]],
                           record["StartingStatuses"], record["IntentRules"])


NEW_ENCOUNTERS = [
    # Act 1 elite #2 (the pool had only the three sentries).
    ("enc_lagavulin", [as_encounter_enemy("lagavulin")]),
    # Act 2 elite #2 and #3 (the pool had only the gremlin leader).
    ("enc_book_of_stabbing", [as_encounter_enemy("book_of_stabbing")]),
    # "Slavers": Taskmaster + Red Slaver + Blue Slaver, in that order (the wiki lists them that way
    # and the order is the turn order).
    ("enc_slavers", [as_encounter_enemy("taskmaster"),
                     as_encounter_enemy("slaver_red"),
                     as_encounter_enemy("blue_slaver")]),
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
for pool, encounter_id in (("Elite", "enc_lagavulin"),
                           ("Elite2", "enc_book_of_stabbing"),
                           ("Elite2", "enc_slavers")):
    rows = tables.setdefault(pool, [])
    if not any(row["Id"] == encounter_id for row in rows):
        rows.append({"Id": encounter_id, "Weight": 1})

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("elite pool now:",
      {pool: [row["Id"] for row in tables[pool]] for pool in ("Elite", "Elite2", "Elite3")})
