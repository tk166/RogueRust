"""§195.4 content: Bronze Orb's `Stasis`, end to end.

Wiki (`native/wiki_asc/bronze_automaton.txt`):

    Stasis  --  Steals a random card of the highest rarity from your draw pile
                (or discard pile, if the draw pile is empty).
                On death, a stolen card is returned to your hand.

Three pieces, two of them new vocabulary:

1. `bronze_orb.stasis` -- `node.selectCards{OwnerSelector: sel.allEnemies, FromZone: DrawPile,
   FallbackZone: DiscardPile, Order: HighestRarity, Count: 1, ToZone: SetAsidePile}`.
   `sel.allEnemies` from an orb is the **opposing** team, i.e. the hero -- the same selector the
   wiki's "your" means.
2. `standard.stasis` (on the orb) -- a `Downed` trigger that moves every card out of the hero's
   `SetAsidePile` back into the hero's hand: `selectCards{Order: First, Count: 4}`. "Returned on
   death" is exactly a death trigger, which the kernel has had since §117.
3. `Stasis` is used **once per combat** (wiki: "can only use Stasis once per combat", 75% chance per
   turn until picked). The once-ness is the status being spent: the action removes its own status,
   and the intent rule that reaches for `stasis` is gated on the status still being there.

Deviations, stated:

* The 75% chance per turn is not modelled (the weighted vocabulary exists since §195.3, but a
  probability per *turn* on one specific move would need a second weighted rule; the orb's other two
  moves stay a plain cycle, which is what §194 already documented).
* "the highest rarity" is the rank Rare > Uncommon > Common > Basic > Status = Curse (§195.4).
"""
import io
import json

SRC = "tools/contentc/packages/sts/sts.roguedeck.json"

document = json.load(io.open(SRC, encoding="utf-8"))
statuses = {row["Id"]: row for row in document["Statuses"]}
actions = {row["Id"]: row for row in document["EnemyActions"]}
monsters = {row["Id"]: row for row in document["Monsters"]}

SOURCE = {"kind": "sel.source",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
ENEMIES = {"kind": "sel.allEnemies", "value": {}}


def program(children):
    root = children[0] if len(children) == 1 else {
        "kind": "node.sequence", "value": {"Children": children}}
    return {"Id": {"Value": "(unnamed)"}, "Root": root, "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def select_cards(owner, from_zone, fallback, order, count, to_zone):
    value = {
        "OwnerSelector": owner,
        "FromZone": from_zone,
        "Order": order,
        "Count": count,
        "ToZone": to_zone,
        "ResultKey": None,
    }
    if fallback is not None:
        value["FallbackZone"] = fallback
    return {"kind": "node.selectCards", "value": value}


# ---------------------------------------------------------------- 1. the status (and its death hook)
if "standard.stasis" not in statuses:
    document["Statuses"].append({
        "Id": "standard.stasis",
        "PackageId": "sts",
        "NameKey": "Stasis",
        "DescriptionKey": "On death, a stolen card is returned to your hand.",
        "Polarity": "Buff",
        "UsesStacks": False,
        "UsesDuration": False,
        "UsesCharges": False,
        "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff", "stasis"],
        "PassiveModifiers": [],
        # Bearer = the orb that just died, so `sel.allEnemies` is resolved **from a Downed source** and
        # can come back empty (that was the first version's bug: the card was never returned).
        # The killer is `sel.eventTarget` (`run_downed_triggers` passes the event's source as the
        # target), and the killer is the hero -- whose `SetAsidePile` holds the stolen card.
        # `Count: 4` is "all of them" in practice (the status steals one).
        "Triggers": [{
            "Event": "Downed",
            "Program": program([
                select_cards({"kind": "sel.eventTarget",
                              "value": {"Cardinality": "ZeroOrOne",
                                        "RequiredContextCapabilities": "EventTarget"}},
                             "SetAsidePile", None, "First", 4, "Hand"),
            ]),
        }],
    })

# ---------------------------------------------------------------- 2. the move
stasis = actions["bronze_orb.stasis"] if "bronze_orb.stasis" in actions else None
if stasis is None:
    record = {
        "Id": "bronze_orb.stasis",
        "PackageId": "sts",
        "NameKey": "Stasis",
        "DescriptionKey": "Stasis - steals the best card in your draw pile",
        "Intent": {"Kind": "Debuff", "Label": "Stasis - steals the best card in your draw pile"},
        "Program": program([
            select_cards(ENEMIES, "DrawPile", "DiscardPile", "HighestRarity", 1, "SetAsidePile"),
            # "can only use Stasis once per combat" = a **separate** flag is spent. It must not be
            # the same status that carries the death hook: consuming that one would delete the hook
            # (first version did exactly that, and the stolen card was never returned).
            {"kind": "node.modifyStatusStacks",
             "value": {"TargetSelector": SOURCE,
                       "StatusDefinitionId": {"value": "standard.stasis_ready"},
                       "Delta": {"kind": "const", "value": {"Value": -99}}}},
        ]),
    }
    document["EnemyActions"].append(record)
    actions[record["Id"]] = record

# ---------------------------------------------------------------- 3. the orb: status + rule
orb = monsters["bronze_orb"]
orb["StartingStatuses"] = [
    # Two statuses on purpose: the hook (returns the card on death, never spent) and the flag
    # ("Stasis not used yet", spent by using it). One status cannot be both.
    {"StatusDefinitionId": {"value": "standard.stasis"}, "Stacks": 1},
    {"StatusDefinitionId": {"value": "standard.stasis_ready"}, "Stacks": 1},
]
orb["IntentRules"] = [{
    # While the flag is there, Stasis is the first thing it does; afterwards the 2-cycle takes over.
    "Condition": {"kind": "intent.selfHasStatus",
                  "value": {"Status": {"value": "standard.stasis_ready"}, "MinStacks": 1}},
    "Action": {"value": "bronze_orb.stasis"},
    "Priority": 50,
}]
orb["Actions"] = [{"value": "bronze_orb.stasis"},
                  {"value": "bronze_orb.beam"},
                  {"value": "bronze_orb.support_beam"}]
orb["AiNote"] = (
    "§194/§195.4：wiki 数值（HP 52-58；Beam 8；Support Beam 给友军 12 Block）。"
    "`Stasis` 现在是真实现：`node.selectCards` 从**玩家的抽牌堆**（空则弃牌堆）挑**稀有度最高**的"
    "一张放进 `SetAsidePile`，`standard.stasis` 的 Downed 触发器在它死亡时把牌还回玩家手牌；"
    "『一场只能用一次』= 用掉的是一条状态。"
    "⚠️ 偏差：① 75% 概率没建模（Orb 的另一招仍是确定性循环）；② Support Beam 用 `sel.allAllies`，"
    "即全体友军（含自己）；③ 两只 Orb 开局在场（§194：遭遇名单是召唤物找招式表的来路）。")

for encounter in document["Encounters"]:
    for record in encounter["Enemies"]:
        if record["Id"] != "bronze_orb":
            continue
        record["StartingStatuses"] = list(orb["StartingStatuses"])
        record["IntentRules"] = json.loads(json.dumps(orb["IntentRules"]))
        record["Actions"] = list(orb["Actions"])

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
print("bronze orb: selectCards-based Stasis + Downed return")
