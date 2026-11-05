"""§227 (part 4): 三张"选完再改它 / 延后复制"的牌。

wiki（`native/wiki_cards/`）：
* `armaments` 1 费 Common Skill —— "Gain 5 Block. Upgrade (a card;all cards) in your hand for the
  rest of combat."；
* `warcry` 0 费 Common Skill —— "Draw (1;2) card(s). Put a card from your hand onto the top of your
  draw pile. Exhaust."；
* `nightmare` 3 费（`+` 2 费）Rare Skill —— "Choose a card. Next turn, add 3 copies of that card into
  your hand. Exhaust."。

Nightmare 的"下一回合"用**内容自己**的载体表达，不碰内核：副本先造进 `SetAsidePile`，再挂一个
`standard.nightmare_pending` 状态，它的 `TurnStarted` 触发器把那一区的牌搬进手牌并自摘。
⇒ 要记住"复制的是哪张牌"的只有**那几份副本本身**（卡实例就是身份），不需要内核存定义 id。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
CHECK = 'native/sts_content_check.py'

SEL_SOURCE = {
    "kind": "sel.source",
    "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"},
}
CONST = lambda n: {"kind": "const", "value": {"Value": n}}  # noqa: E731


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def gain_block(amount):
    return node("node.gainBlock", TargetSelector=SEL_SOURCE, Amount=CONST(amount),
                PoolId={"value": "standard.block"})


def draw(count):
    # ⚠️ 抽牌节点的 owner 字段叫 **TargetSelector**（`draw_cards_node` 读它；实测见
    # `pommel_strike`）。写成 `OwnerSelector` 不会报错到内容层 —— 内核会在派发期说"缺字段"。
    return node("node.drawCards", TargetSelector=SEL_SOURCE, Count=CONST(count))


def choose(minimum, maximum, then, **extra):
    value = dict(OwnerSelector=SEL_SOURCE, FromZone="Hand", Min=minimum, Max=maximum, **extra)
    if then is not None:
        value["Then"] = then
    return node("node.chooseCards", **value)


def upgrade_all_in_hand():
    return node("node.upgradeCards", OwnerSelector=SEL_SOURCE, FromZone="Hand")


def apply_status(status, stacks):
    return node("node.applyStatus", TargetSelector=SEL_SOURCE,
                StatusDefinitionId={"value": status}, Stacks=CONST(stacks),
                DurationTurns=0, Charges=0)


def card(cid, name, text, cost, rarity, root, played_zone, keywords=()):
    tags = ["skill"] + [word.lower() for word in keywords]
    return {
        "Id": cid,
        "PackageId": "sts",
        "NameKey": name,
        "DescriptionKey": text,
        "Costs": [{"ResourceId": {"value": "standard.energy"}, "Amount": cost}],
        "Tags": [{"value": tag} for tag in tags],
        "Rarity": rarity,
        "Program": {"Id": {"Value": "(unnamed)"}, "Root": root,
                    "MaxNodeDepth": 64, "MaxProgramSteps": 1024},
        "LifecyclePrograms": {},
        "RetainInHandOnTurnEnd": False,
        "TurnEndHandDestinationZone": "DiscardPile",
        "PlayedCardDestinationZone": played_zone,
    }


# ── Nightmare 的"下一回合"载体 ────────────────────────────────────────────────
MOVE_EACH_TO_HAND = node(
    "node.moveCardToZone",
    CardExpression={"kind": "cardInstance.iterated", "value": {}},
    OwnerSelector=SEL_SOURCE,
    ToZone="Hand",
    Placement="Bottom",
)

NIGHTMARE_PENDING = {
    "Id": "standard.nightmare_pending",
    "PackageId": "sts",
    "NameKey": "Nightmare",
    "DescriptionKey": "At the start of your next turn, add the copies Nightmare set aside to your hand.",
    "Polarity": "Buff",
    "UsesStacks": True,
    "UsesDuration": False,
    "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["buff"],
    "PassiveModifiers": [],
    "Triggers": [{
        "Event": "TurnStarted",
        "Program": {
            "Id": {"Value": "(unnamed)"},
            "Root": node(
                "node.sequence",
                Children=[
                    node("node.forEachCardInZone", OwnerSelector=SEL_SOURCE,
                         Zone="SetAsidePile", MaxIterations=64, Body=MOVE_EACH_TO_HAND),
                    node("node.modifyStatusStacks", TargetSelector=SEL_SOURCE,
                         StatusDefinitionId={"value": "standard.nightmare_pending"},
                         Delta=CONST(-99)),
                ],
            ),
            "MaxNodeDepth": 64,
            "MaxProgramSteps": 1024,
        },
    }],
}

ARMAMENTS_BASE = node("node.sequence", Children=[gain_block(5), choose(1, 1, "Upgrade")])
ARMAMENTS_PLUS = node("node.sequence", Children=[gain_block(5), upgrade_all_in_hand()])
WARCRY_BASE = node("node.sequence", Children=[draw(1), choose(1, 1, "ToDrawPileTop")])
WARCRY_PLUS = node("node.sequence", Children=[draw(2), choose(1, 1, "ToDrawPileTop")])
NIGHTMARE = node("node.sequence", Children=[
    choose(1, 1, "Copy", Copies=3, ToZone="SetAsidePile"),
    apply_status("standard.nightmare_pending", 1),
])

raw = io.open(CONTENT, encoding='utf-8').read()
data = json.loads(raw)
have = {row['Id'] for row in data['Cards']} | {row['Id'] for row in data['Statuses']}
assert not (have & {'armaments', 'warcry', 'nightmare', 'standard.nightmare_pending'})

data['Cards'].append(card(
    'armaments', 'Armaments',
    "Gain 5 Block. Upgrade a card in your hand for the rest of combat.",
    1, 'Common', ARMAMENTS_BASE, 'DiscardPile'))
data['Cards'].append(card(
    'armaments+', 'Armaments+',
    "Gain 5 Block. Upgrade all cards in your hand for the rest of combat.",
    1, 'Common', ARMAMENTS_PLUS, 'DiscardPile'))
data['Cards'].append(card(
    'warcry', 'Warcry',
    "Draw 1 card. Put a card from your hand onto the top of your draw pile. Exhaust.",
    0, 'Common', WARCRY_BASE, 'ExhaustPile'))
data['Cards'].append(card(
    'warcry+', 'Warcry+',
    "Draw 2 cards. Put a card from your hand onto the top of your draw pile. Exhaust.",
    0, 'Common', WARCRY_PLUS, 'ExhaustPile'))
data['Cards'].append(card(
    'nightmare', 'Nightmare',
    "Choose a card. Next turn, add 3 copies of that card into your hand. Exhaust.",
    3, 'Rare', NIGHTMARE, 'ExhaustPile'))
data['Cards'].append(card(
    'nightmare+', 'Nightmare+',
    "Choose a card. Next turn, add 3 copies of that card into your hand. Exhaust.",
    2, 'Rare', NIGHTMARE, 'ExhaustPile'))
data['Statuses'].append(NIGHTMARE_PENDING)

out = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
assert out != raw
io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(out)

# ── checker：事实 walk 认识新的 `Then`/`ToZone`，并加三张牌（`+` 行）的清单 ──────
src = io.open(CHECK, encoding='utf-8').read()
old = '''        elif kind == "node.chooseCards":
            # §226: "ask the player which cards, then copy them" as one fact. **Every** field that
            # decides the question is part of it -- "an Attack or Power" vs "any card" is exactly
            # the difference between Dual Wield and a card that does not exist yet.
            out.append(("chooseCopy", tgt(body["OwnerSelector"]), body["FromZone"],
                          tuple(body.get("RequireAnyTag") or ()),
                          body["Min"], body["Max"], body["Copies"]))'''
new = '''        elif kind == "node.chooseCards":
            # §226/§227: "ask the player which cards, then do X to them" as one fact. **Every** field
            # that decides the question is part of it -- "an Attack or Power" vs "any card" vs "only
            # cards with a `+` row" is exactly the difference between these cards.
            then = body["Then"]
            extra = ()
            if then == "Copy":
                extra = (body.get("ToZone", "Hand"), body["Copies"])
            out.append(("choose", tgt(body["OwnerSelector"]), body["FromZone"],
                          tuple(body.get("RequireAnyTag") or ()),
                          body["Min"], body["Max"], then) + extra)'''
assert src.count(old) == 1
src = src.replace(old, new)

old = '''        elif kind == "node.upgradeCards":'''
assert src.count(old) == 1
# `upgradeCards` 的事实要区分"按定义升级"与"整片牌区升级"（CardDefinitionId 现在可缺席）。
src = src.replace('''        elif kind == "node.upgradeCards":''',
                  '''        elif kind == "node.upgradeCards":''')

old = '''    # 落区是 **DiscardPile**：`native/wiki_cards/dual_wield.txt` 的 Infobox 里没有 Exhaust，
    # 正文也只说 "add 1 copy (2 copies if upgraded) of that card into your hand"。
    "dual_wield": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("chooseCopy", "source", "Hand", ("attack", "power"), 1, 1, 1)],
                   "PlayedCardDestinationZone": "DiscardPile"},
    "dual_wield+": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [("chooseCopy", "source", "Hand", ("attack", "power"), 1, 1, 2)],
                    "PlayedCardDestinationZone": "DiscardPile"},'''
new = '''    # 落区是 **DiscardPile**：`native/wiki_cards/dual_wield.txt` 的 Infobox 里没有 Exhaust，
    # 正文也只说 "add 1 copy (2 copies if upgraded) of that card into your hand"。
    # §227: the fact gained the `Then` (and, for `Copy`, where the copies land).
    "dual_wield": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("choose", "source", "Hand", ("attack", "power"), 1, 1, "Copy",
                              "Hand", 1)],
                   "PlayedCardDestinationZone": "DiscardPile"},
    "dual_wield+": {"Cost": 1, "Tags": ["skill"],
                    "Facts": [("choose", "source", "Hand", ("attack", "power"), 1, 1, "Copy",
                               "Hand", 2)],
                    "PlayedCardDestinationZone": "DiscardPile"},
    # ---- §227：选完再改它 / 延后复制 ---------------------------------------------------------
    # `armaments+` 的 `upgradeCards` 没有 `CardDefinitionId`（"整片手牌"）—— 这一条事实里
    # 那个字段是 `None`，所以"升级了哪张"与"升级了整片"在清单上不可能被混起来。
    "armaments": {"Cost": 1, "Tags": ["skill"],
                  "Facts": [("block", 5, "source"),
                            ("choose", "source", "Hand", (), 1, 1, "Upgrade")],
                  "PlayedCardDestinationZone": "DiscardPile"},
    "armaments+": {"Cost": 1, "Tags": ["skill"],
                   "Facts": [("block", 5, "source"),
                             ("upgrade", "source", None, "Hand")],
                   "PlayedCardDestinationZone": "DiscardPile"},
    "warcry": {"Cost": 0, "Tags": ["skill"],
               "Facts": [("draw", 1),
                         ("choose", "source", "Hand", (), 1, 1, "ToDrawPileTop")],
               "PlayedCardDestinationZone": "ExhaustPile"},
    "warcry+": {"Cost": 0, "Tags": ["skill"],
                "Facts": [("draw", 2),
                          ("choose", "source", "Hand", (), 1, 1, "ToDrawPileTop")],
                "PlayedCardDestinationZone": "ExhaustPile"},
    "nightmare": {"Cost": 3, "Tags": ["skill"],
                  "Facts": [("choose", "source", "Hand", (), 1, 1, "Copy", "SetAsidePile", 3),
                            ("status", "standard.nightmare_pending", 1, "source")],
                  "PlayedCardDestinationZone": "ExhaustPile"},
    "nightmare+": {"Cost": 2, "Tags": ["skill"],
                   "Facts": [("choose", "source", "Hand", (), 1, 1, "Copy", "SetAsidePile", 3),
                             ("status", "standard.nightmare_pending", 1, "source")],
                   "PlayedCardDestinationZone": "ExhaustPile"},'''
assert src.count(old) == 1
src = src.replace(old, new)
io.open(CHECK, 'w', encoding='utf-8', newline='\n').write(src)
print('ok content')
