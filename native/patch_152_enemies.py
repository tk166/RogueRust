"""§152: more act-1 enemies, with the wiki's numbers.

The complaint that started this: "现在的品类太单一了而且数值也不合理". The act-1 weak pool had three
encounters and the elite pool one; every fight looked the same and the only numbers anyone could
check were already there.

Everything here uses mechanics the kernel already has (damage / block / status / strength) -- no new
subsystem. Numbers from the wiki:

| enemy | HP | moves |
|---|---|---|
| Red Louse | 10-15 | Bite 5-7, Grow (+3 Strength), Spit Web (2 Weak) |
| Green Louse | 11-16 | Bite 5-7, Grow (+3 Strength) |
| Fungi Beast | 22-28 | Bite 6, Grow (+3 Strength) |
| Red Slaver | 46-50 | Stab 13, Scrape 7 + 1 Weak |
| Gremlin Nob (elite) | 82-86 | Bellow (+2 Strength), Rush 14, Skull Bash 6 + 2 Vulnerable |

The HP ranges collapse to `HpMin` for `MaxHealth` because the kernel's `FightPlan` carries one
integer (see Notes.Deviations); the range is kept in the roster for the inventory.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_152_enemies.py
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

actions = document["EnemyActions"]
encounters = document["Encounters"]
monsters = document["Monsters"]
existing_actions = {action["Id"] for action in actions}


def selector(kind, capability):
    return {"kind": kind,
            "value": {"Cardinality": "ZeroOrOne",
                      "RequiredContextCapabilities": capability}}


def program(children):
    return {
        "Id": {"Value": "(unnamed)"},
        "Root": {"kind": "node.sequence", "value": {"Children": children}}
        if len(children) > 1
        else children[0],
        "MaxNodeDepth": 64,
        "MaxProgramSteps": 1024,
    }


def damage(amount, target="event"):
    return {
        "kind": "node.dealDamage",
        "value": {
            "TargetSelector": selector("sel.eventTarget", "EventTarget" if target == "event" else "Source"),
            "Amount": {"kind": "const", "value": {"Value": amount}},
            "ResultKey": None,
            "IgnoresBlock": False,
            "Element": None,
        },
    }


def status(status_id, stacks, target="event"):
    return {
        "kind": "node.applyStatus",
        "value": {
            "TargetSelector": selector("sel.eventTarget", "EventTarget" if target == "event" else "Source"),
            "StatusDefinitionId": {"value": status_id},
            "Stacks": {"kind": "const", "value": {"Value": stacks}},
            "DurationTurns": 0,
            "Charges": 0,
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


NEW_ACTIONS = [
    # ---- Red Louse ----
    action("louse_red.bite", "Bite", "Bite - 6 damage", "Attack", [damage(6)]),
    action("louse_red.grow", "Grow", "Grow - 3 Strength", "Buff",
           [status("standard.strength", 3, "source")]),
    action("louse_red.spit_web", "Spit Web", "Spit Web - 2 Weak", "Debuff",
           [status("standard.weak", 2)]),
    # ---- Green Louse ----
    action("louse_green.bite", "Bite", "Bite - 6 damage", "Attack", [damage(6)]),
    action("louse_green.grow", "Grow", "Grow - 3 Strength", "Buff",
           [status("standard.strength", 3, "source")]),
    # ---- Fungi Beast ----
    action("fungi_beast.bite", "Bite", "Bite - 6 damage", "Attack", [damage(6)]),
    action("fungi_beast.grow", "Grow", "Grow - 3 Strength", "Buff",
           [status("standard.strength", 3, "source")]),
    # ---- Red Slaver ----
    action("slaver_red.stab", "Stab", "Stab - 13 damage", "Attack", [damage(13)]),
    action("slaver_red.scrape", "Scrape", "Scrape - 7 damage, 1 Weak", "Attack",
           [damage(7), status("standard.weak", 1)]),
    # ---- Gremlin Nob (elite) ----
    action("gremlin_nob.bellow", "Bellow", "Bellow - 2 Strength", "Buff",
           [status("standard.strength", 2, "source")]),
    action("gremlin_nob.rush", "Rush", "Rush - 14 damage", "Attack", [damage(14)]),
    action("gremlin_nob.skull_bash", "Skull Bash", "Skull Bash - 6 damage, 2 Vulnerable", "Attack",
           [damage(6), status("standard.vulnerable", 2)]),
]
for record in NEW_ACTIONS:
    if record["Id"] not in existing_actions:
        actions.append(record)


def enemy(monster_id, display, max_health, action_ids):
    return {
        "Id": monster_id,
        "MaxHealth": max_health,
        "Actions": [{"value": action_id} for action_id in action_ids],
        "StartingStatuses": [],
        "Position": 0,
        "IntentRules": [],
        "DisplayName": display,
    }


NEW_ENCOUNTERS = [
    ("enc_louse", [enemy("louse_red", "Red Louse", 10,
                         ["louse_red.bite", "louse_red.grow", "louse_red.spit_web"])]),
    ("enc_fungi_beast", [enemy("fungi_beast", "Fungi Beast", 22,
                               ["fungi_beast.bite", "fungi_beast.grow"])]),
    ("enc_slaver_red", [enemy("slaver_red", "Slaver", 46,
                              ["slaver_red.stab", "slaver_red.scrape"])]),
    # An elite: the act-1 elite pool was one encounter (three sentries).
    ("enc_gremlin_nob", [enemy("gremlin_nob", "Gremlin Nob", 82,
                               ["gremlin_nob.bellow", "gremlin_nob.rush", "gremlin_nob.skull_bash"])]),
]
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

NEW_MONSTERS = [
    ("louse_red", "Red Louse", 10, 15, ["louse_red.bite", "louse_red.grow", "louse_red.spit_web"]),
    ("louse_green", "Green Louse", 11, 16, ["louse_green.bite", "louse_green.grow"]),
    ("fungi_beast", "Fungi Beast", 22, 28, ["fungi_beast.bite", "fungi_beast.grow"]),
    ("slaver_red", "Red Slaver", 46, 50, ["slaver_red.stab", "slaver_red.scrape"]),
    ("gremlin_nob", "Gremlin Nob", 82, 86,
     ["gremlin_nob.bellow", "gremlin_nob.rush", "gremlin_nob.skull_bash"]),
]
existing_monsters = {monster["Id"] for monster in monsters}
for monster_id, name, low, high, action_ids in NEW_MONSTERS:
    if monster_id in existing_monsters:
        continue
    monsters.append({
        "Id": monster_id,
        "NameKey": name,
        "HpMin": low,
        "HpMax": high,
        "MaxHealth": low,
        "Actions": [{"value": action_id} for action_id in action_ids],
        "StartingStatuses": [],
        "IntentRules": [],
        "Tier": "Normal",
        "InvRef": "https://slaythespire.wiki.gg/wiki/" + name.replace(" ", "_"),
        "AiNote": "§152：wiki 的 1 幕怪；数值见 patch_152_enemies.py 的表格。",
    })

tables = document["EncounterTables"]
for pool, encounter_id in (("Weak", "enc_louse"), ("Weak", "enc_fungi_beast"),
                           ("Weak", "enc_slaver_red"), ("Elite", "enc_gremlin_nob")):
    rows = tables.setdefault(pool, [])
    if not any(row["Id"] == encounter_id for row in rows):
        rows.append({"Id": encounter_id})

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("monsters:", len(monsters), "actions:", len(actions), "encounters:", len(encounters))
print("weak :", [row["Id"] for row in tables["Weak"]])
print("elite:", [row["Id"] for row in tables.get("Elite", [])])
