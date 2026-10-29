"""Add Whirlwind (§146): the first X-cost card, and the first `node.repeat` in this content.

Whirlwind (Ironclad, Uncommon, Attack): `X` cost, "Deal 5 damage to ALL enemies X times."
(upgraded: 8). The X is the energy the play consumed — see `port-plan.md` §146.

Run:  python D:\\Vibe\\sts-tui\\native\\patch_146_whirlwind.py
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

cards = document["Cards"]
if any(card["Id"] == "whirlwind" for card in cards):
    raise SystemExit("already patched: whirlwind exists")

template = next(card for card in cards if card["Id"] == "sentinel")
record = json.loads(json.dumps(template))
record["Id"] = "whirlwind"
record["NameKey"] = "Whirlwind"
record["DescriptionKey"] = "Deal 5 damage to ALL enemies X times."
record["Rarity"] = "Uncommon"
# X 费：资源名写出来（读者一眼看到花的是能量），`Amount` 必须是 0 —— 它不参与结算。
record["Costs"] = [{"ResourceId": {"value": "standard.energy"}, "Amount": 0}]
record["Tags"] = [{"value": "attack"}, {"value": "x_cost"}]
record["RetainInHandOnTurnEnd"] = False
record["TurnEndHandDestinationZone"] = "DiscardPile"
record["PlayedCardDestinationZone"] = "DiscardPile"
record["Program"]["Root"] = {
    "kind": "node.repeat",
    "value": {
        # X 遍：`x.cost` 是这一次出牌真的花掉的能量。
        "Count": {"kind": "x.cost"},
        "Body": {
            "kind": "node.dealDamage",
            "value": {
                "TargetSelector": {
                    "kind": "sel.allEnemies",
                    "value": {"Cardinality": "Any"},
                },
                "Amount": {"kind": "const", "value": {"Value": 5}},
                "ResultKey": None,
                "IgnoresBlock": False,
                "Element": None,
            },
        },
        # 参考的 `RepeatEffectNode.DefaultMaxCount`；超过它内核会**抛**，不截断。
        "MaxCount": 32,
    },
}
cards.append(record)

with io.open(SRC, "w", encoding="utf-8", newline="\n") as handle:
    json.dump(document, handle, ensure_ascii=False, indent=2)
    handle.write("\n")

print("cards:", len(cards))
