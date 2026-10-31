"""§158: 药水稀有档补到 wiki 的数目（铁甲战士口径 17 / 9 / 7 = 33），第一步：便宜的九瓶。

这个脚本只动内容 JSON（`json.dump(indent=2, ensure_ascii=False)` 已实测与该文件逐字节
往返一致，见 `native/probe_json_roundtrip.py`）：

1. 新状态 `standard.dexterity`（格挡折叠走内容侧的 `BlockGain` spec，参考
   `StandardCombatPackage.cs:360-363`：AddPerStack / 1 / Priority 100）；
2. 新状态 `standard.lose_strength` / `standard.lose_dexterity`（Flex/Speed 药水的"回合末还回去"）：
   `TurnEnded` 触发器把 `standard.strength` 减去自身层数，再把自己减到 0；
3. 九瓶新药水；`energy_potion` 稀有度改成 Common（wiki 它是 Common，内容里写成了 Uncommon）；
4. 删掉 `PotionTables`：三幕各自一份药水池是**没有出处的自造**（wiki 里药水不分幕），
   而 `MAX_POOL_IDS = 8` 会把 33 瓶静默截成 8 瓶 —— 这是本项目最忌讳的那种"声明了但被截断"。
"""

import json
import pathlib

PATH = pathlib.Path("tools/contentc/packages/sts/sts.roguedeck.json")


def source_selector():
    return {
        "kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
    }


def status_stacks_expr(status_id):
    return {
        "kind": "combatantStatusStacks",
        "value": {"Selector": source_selector(), "StatusId": {"value": status_id}},
    }


def negate_stacks(status_id):
    """`-stacks(status_id)` = `subtract(const 0, combatantStatusStacks(...))`（内核没有 `negate`）。"""
    return {
        "kind": "subtract",
        "value": {
            "Left": {"kind": "const", "value": {"Value": 0}},
            "Right": status_stacks_expr(status_id),
        },
    }


def modify(target_status, delta):
    return {
        "kind": "node.modifyStatusStacks",
        "value": {
            "TargetSelector": source_selector(),
            "StatusDefinitionId": {"value": target_status},
            "Delta": delta,
            "ResultKey": None,
        },
    }


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root, "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def turn_ended(root):
    return {"Event": "TurnEnded", "Program": program(root)}


def status(sid, name, description, polarity, tags, passive, triggers):
    return {
        "Id": sid,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": description,
        "Polarity": polarity,
        "UsesStacks": True,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": tags,
        "PassiveModifiers": passive,
        "Triggers": triggers,
        "DeathPrevention": None,
        "DebuffBlock": None,
        "IncomingStatusDelay": None,
        "Disclosure": None,
    }


def block_spec(operation, magnitude, priority):
    return {
        "Pipeline": "BlockGain",
        "Operation": operation,
        "Magnitude": magnitude,
        "Priority": priority,
        "RestrictDamageKind": None,
        "AppliesToStatusId": None,
        "RestrictSourceCardTag": None,
    }


DEXTERITY = status(
    "standard.dexterity",
    "Dexterity",
    "Cards that give Block give 1 more per stack.",
    "Buff",
    ["buff", "dexterity"],
    [block_spec("AddPerStack", 1, 100)],
    [],
)


def lose_status(sid, name, target, description):
    return status(
        sid,
        name,
        description,
        "Debuff",
        ["debuff"],
        [],
        [
            turn_ended(
                {
                    "kind": "node.sequence",
                    "value": {
                        "Children": [
                            modify(target, negate_stacks(sid)),
                            modify(sid, negate_stacks(sid)),
                        ]
                    },
                }
            )
        ],
    )


LOSE_STRENGTH = lose_status(
    "standard.lose_strength",
    "Lose Strength",
    "standard.strength",
    "At the end of the turn, lose Strength equal to this status's stacks, then remove it.",
)
LOSE_DEXTERITY = lose_status(
    "standard.lose_dexterity",
    "Lose Dexterity",
    "standard.dexterity",
    "At the end of the turn, lose Dexterity equal to this status's stacks, then remove it.",
)


def potion(pid, name, description, effect, amount, rarity):
    return {
        "Id": pid,
        "NameKey": name,
        "DescriptionKey": description,
        "Effect": effect,
        "Amount": amount,
        "Rarity": rarity,
    }


# 九瓶新的。Effect 用逗号串可以带多个原子（§158）—— Flex/Speed 需要它。
NEW_POTIONS = [
    potion(
        "ancient_potion",
        "Ancient Potion",
        "Gain 1 Artifact.",
        "combat_status:standard.artifact",
        1,
        "Uncommon",
    ),
    potion(
        "dexterity_potion",
        "Dexterity Potion",
        "Gain 2 Dexterity.",
        "combat_status:standard.dexterity",
        2,
        "Common",
    ),
    potion(
        "essence_of_steel",
        "Essence of Steel",
        "Gain 4 Plated Armor.",
        "combat_status:standard.plated_armor",
        4,
        "Uncommon",
    ),
    potion(
        "liquid_bronze",
        "Liquid Bronze",
        "Gain 3 Thorns.",
        "combat_status:standard.thorns",
        3,
        "Uncommon",
    ),
    potion(
        "heart_of_iron",
        "Heart of Iron",
        "Gain 6 Metallicize.",
        "combat_status:standard.metallicize",
        6,
        "Rare",
    ),
    potion(
        "cultist_potion",
        "Cultist Potion",
        "Gain 1 Ritual.",
        "combat_status:ritual",
        1,
        "Rare",
    ),
    potion(
        "flex_potion",
        "Flex Potion",
        "Gain 5 Strength. At the end of your turn, lose 5 Strength.",
        "combat_status:standard.strength,combat_status:standard.lose_strength",
        5,
        "Common",
    ),
    potion(
        "speed_potion",
        "Speed Potion",
        "Gain 5 Dexterity. At the end of your turn, lose 5 Dexterity.",
        "combat_status:standard.dexterity,combat_status:standard.lose_dexterity",
        5,
        "Common",
    ),
    # 0 是"这个效果不读数量"—— 具体见 [3b] 里的 `POTION_NO_AMOUNT`。
    potion(
        "entropic_brew",
        "Entropic Brew",
        "Fill all your empty potion slots with random potions.",
        "potion_fill",
        0,
        "Rare",
    ),
]

# `energy_potion` 在内容里写成 Uncommon，wiki 是 Common（"Energy Potion | Common"）。
RARITY_FIXES = {"energy_potion": "Common"}


def main():
    raw = PATH.read_bytes()
    doc = json.loads(raw.decode("utf-8"))

    statuses = doc["Statuses"]
    have = {row["Id"] for row in statuses}
    for row in (DEXTERITY, LOSE_STRENGTH, LOSE_DEXTERITY):
        if row["Id"] in have:
            raise SystemExit("状态 %s 已经存在" % row["Id"])
        statuses.append(row)

    potions = doc["Potions"]
    have = {row["Id"] for row in potions}
    if "entropic_brew" in have:
        raise SystemExit("药水已经补过了")
    for row in NEW_POTIONS:
        if row["Id"] in have:
            raise SystemExit("药水 %s 已经存在" % row["Id"])
        potions.append(row)
    for row in potions:
        if row["Id"] in RARITY_FIXES:
            row["Rarity"] = RARITY_FIXES[row["Id"]]

    if "PotionTables" not in doc:
        raise SystemExit("PotionTables 已经删过了")
    del doc["PotionTables"]

    out = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    PATH.write_bytes(out.encode("utf-8"))

    bands = {}
    for row in potions:
        bands[row["Rarity"]] = bands.get(row["Rarity"], 0) + 1
    print("potions", len(potions), bands)
    print("statuses", len(statuses))


if __name__ == "__main__":
    main()
