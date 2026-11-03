"""§195.2: Awakened One revives **for real** -- and it needed no new primitive.

§194's degradation said "the kernel has no death interceptor, so the boss revives before dying (at
<= 25% HP)". That was wrong in two ways, and this patch is the correction:

1. The kernel **does** intercept death: `exec::resolve_damage` runs every `DeathPrevention` status on
   the target *before* the HP is written (`exec.rs`, the `S6d` block, §180 -- Fairy in a Bottle). It is
   generic over combatants: nothing in it is player-only.
2. The wiki's own timeline matches that hook: StS sets `halfDead` on the phase-1 death and heals at the
   boss's next turn. With `DeathPrevention{SurvivingHealth: 1}` per our content, the observable is the
   same: the killing blow leaves the boss standing, and its next intent heals it to full.

So the fix is content:

    status standard.unawakened   DeathPrevention { SurvivingHealth: 1, Repeating: false }
      -> spent on the first lethal blow (the kernel already consumes non-repeating ones)

    intent rule  not(selfHasStatus standard.unawakened)  -> awakened_one.rebirth
      -> fires exactly once, right after the guard is spent (no percentage to guess)

    rebirth      heal to full + drop Curiosity + set the phase counters (already written in §194)

⚠️ One deliberate deviation, stated: StS's phase 1 has **0 HP** when it is `halfDead`; ours sits at
**1 HP** (that is what `DeathPrevention` means). The player can therefore kill it before it revives --
one more hit lands and it dies for good. It is the same "you must kill it twice" rule with the second
kill allowed one turn earlier.
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
statuses = {row["Id"]: row for row in document["Statuses"]}
monsters = {row["Id"]: row for row in document["Monsters"]}

if "standard.unawakened" not in statuses:
    document["Statuses"].append({
        "Id": "standard.unawakened",
        "PackageId": "sts",
        "NameKey": "Unawakened",
        "DescriptionKey": "The first lethal blow leaves it at 1 HP; it awakens instead of dying.",
        "Polarity": "Buff",
        "UsesStacks": False,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "RefreshDuration",
        "Tags": ["buff", "unawakened"],
        "PassiveModifiers": [],
        "Triggers": None,
        # `Repeating: false` = spent on use (`exec.rs` consumes a non-repeating guard), which is what
        # makes "the second killing blow kills" true and is why the intent rule can be
        # `not(hasStatus)` instead of a health percentage.
        "DeathPrevention": {"SurvivingHealth": 1, "Percent": 0, "Repeating": False},
    })

awakened = monsters["awakened_one"]
awakened["StartingStatuses"] = [
    {"StatusDefinitionId": {"value": "standard.regen"}, "Stacks": 10},
    {"StatusDefinitionId": {"value": "standard.curiosity"}, "Stacks": 1},
    {"StatusDefinitionId": {"value": "standard.unawakened"}, "Stacks": 1},
]

# Rebirth is now keyed on "the guard is spent", not on a health percentage.
# ⚠️ Both halves are needed: "the guard is spent" alone is true **forever** after the first death, so
# the rule would re-fire Rebirth every turn and the boss would never fight. `ao_phase <= 0` is the
# "not reborn yet" flag that Rebirth itself sets.
rebirth_rule = {
    "Condition": {"kind": "intent.allOf", "value": {"Conditions": [
        {"kind": "intent.not", "value": {"Condition": {
            "kind": "intent.selfHasStatus",
            "value": {"Status": {"value": "standard.unawakened"}, "MinStacks": 1}}}},
        {"kind": "intent.selfHasCounter",
         "value": {"Counter": {"value": "ao_phase"}, "Op": "LessOrEqual", "Value": 0}},
    ]}},
    "Action": {"value": "awakened_one.rebirth"},
    "Priority": 95,
}
others = [rule for rule in awakened["IntentRules"]
          if rule["Action"]["value"] != "awakened_one.rebirth"]
awakened["IntentRules"] = [rebirth_rule] + others
awakened["AiNote"] = (
    "§194/§195.2：wiki 数值（HP 300/320；Regenerate 10 / A19 15；Curiosity 1 / A19 2；Slash 20；"
    "Soul Strike 6×4；Dark Echo 40；Tackle 10×3；Sludge 18 + 1 Void）。两阶段用计数器做："
    "`ao_phase` 由 Rebirth 置 1，之后 Dark Echo（一次）→ Tackle/Sludge 交替。"
    "**复活是真的**：`standard.unawakened` 带 `DeathPrevention{1 HP, 一次性}`，第一次致命伤把它留在"
    "1 血并消耗掉，意图规则 `not(hasStatus unawakened)` ⇒ 下一回合 Rebirth（回满血 + 摘 Curiosity）。"
    "⚠️ 偏差：① StS 的两阶段第一阶段是 **0 血**（halfDead），我们停在 1 血 —— 所以玩家可以在它"
    "复活前补一刀直接杀死（同『要杀两次』的规则，第二次早一回合）；② 『移除所有 debuff』只按名摘掉"
    "Curiosity；③ 两个 Cultist 不在；④ Regenerate/Curiosity 的层数不随 A19 变"
    "（`StartingStatuses` 没有升档轴 —— `Counters` 有，这两条还没有）。")

for encounter in document["Encounters"]:
    for record in encounter["Enemies"]:
        if record["Id"] == "awakened_one":
            record["StartingStatuses"] = list(awakened["StartingStatuses"])
            record["IntentRules"] = list(awakened["IntentRules"])

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("awakened one: DeathPrevention guard + not(hasStatus) rule")
