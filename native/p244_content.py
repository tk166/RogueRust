"""§244（内容）：① 给无色牌加 `colorless` tag；② B 档 8 张。

## ① `colorless` tag —— 一个**内容约定**，内核不用改

`jack_of_all_trades` / `transmutation` / `magnetism` / `chrysalis`(不) 要"随机**无色**牌"，
而本内容的 tag 一直是 `attack/skill/power/status/curse` 这组**类型** tag，没有"颜色"维度。
§240 的随机池本来就是"按 tag 过滤"，所以补一个 `colorless` tag 就够了 —— **零内核改动**。

⚠️ 只给**真·无色牌**打这个 tag（不含 status/curse）：`wound` / `dazed` 在数据模块里也是
`Color = Colorless`，但 StS 的"随机无色牌"池子从不给它们，把 tag 一起打上去会让
`jack_of_all_trades` 发一张 `Wound`。

## ② B 档 8 张（数字来自 `native/wiki_cards/<id>.txt`）

| 牌 | 费用 | 原文 | 载体 |
|---|---|---|---|
| `mayhem` | 2/1 | At the start of your turn, play the top card of your draw pile. | §241 `playTopCardOfDrawPile`（**零改动**） |
| `chrysalis` | 2 | Shuffle (3;5) random Skills into your draw pile. They cost 0 this combat. Exhaust. | §240 随机造牌 + `ToZone: DrawPile` |
| `metamorphosis` | 2 | 同上，Attacks | 同上 |
| `jack_of_all_trades` | 0 | Add (1;2) random Colorless (card;cards) into your hand. Exhaust. | §240 + `colorless` tag |
| `magnetism` | 2/1 | At the start of your turn, add a random Colorless card into your hand. | §237 `TurnStarted` + §240 |
| `secret_technique` | 0 | Put a Skill from your draw pile into your hand. Exhaust.（升级去掉 Exhaust） | §244 `ChoiceSource::DrawPile` |
| `secret_weapon` | 0 | 同上，Attack | 同上 |
| `violence` | 0 | Put (3;4) random Attacks from your draw pile into your hand. Exhaust. | `node.selectCards{Order: Random}`（**零改动**） |
| `purity` | 0 | Exhaust up to (3;5) cards in your hand. Exhaust. | `chooseCards{Then: Exhaust}`（**零改动**） |
| `transmutation` | X | Add X random Colorless cards into your hand. They cost 0 this turn. Exhaust. | §240 + `x.cost` 当 `Count` |
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
SEL_TARGET = {"kind": "sel.eventTarget",
              "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def x_cost():
    return {"kind": "x.cost", "value": {}}


def sequence(*children):
    return node("node.sequence", Children=list(children))


def apply_status(status, stacks=1):
    return node("node.applyStatus", TargetSelector=SEL_SELF,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def random_cards(tag, zone, count, cost_zero=True):
    return node("node.createRandomCardInstance", Tag=tag, ToZone=zone,
                Count=count if isinstance(count, dict) else const(count),
                CostZero=cost_zero)


def play_top_of_draw_pile():
    return node("node.playTopCardOfDrawPile")


def select_from_draw_pile(tag, count):
    return node("node.selectCards", OwnerSelector=SEL_SELF, FromZone="DrawPile",
                Order="Random", Count=count, ToZone="Hand", RequireTag=tag)


def choose_from_draw_pile(tag):
    return node("node.chooseCards", OwnerSelector=SEL_SELF, FromZone="DrawPile",
                Min=1, Max=1, Then="ToHand", ToZone="Hand", RequireAnyTag=[tag])


def choose_exhaust_up_to(max_cards):
    return node("node.chooseCards", OwnerSelector=SEL_SELF, FromZone="Hand",
                Min=1, Max=max_cards, Then="Exhaust", ToZone="Hand")


CARDS = [
    # ---- 触发器 + 随机造牌 ----
    dict(id='mayhem', name='Mayhem', cost=2, rarity='Rare', tags=['power'],
         text='At the start of your turn, play the top card of your draw pile.',
         root=apply_status('standard.mayhem', 1)),
    dict(id='mayhem+', name='Mayhem+', cost=1, rarity='Rare', tags=['power'],
         text='At the start of your turn, play the top card of your draw pile.',
         root=apply_status('standard.mayhem', 1)),
    dict(id='magnetism', name='Magnetism', cost=2, rarity='Rare', tags=['power'],
         text='At the start of your turn, add a random Colorless card into your hand.',
         root=apply_status('standard.magnetism', 1)),
    dict(id='magnetism+', name='Magnetism+', cost=1, rarity='Rare', tags=['power'],
         text='At the start of your turn, add a random Colorless card into your hand.',
         root=apply_status('standard.magnetism', 1)),
    # ---- 随机造牌（进抽牌堆 / 进手牌） ----
    dict(id='chrysalis', name='Chrysalis', cost=2, rarity='Rare', tags=['skill'],
         text='Shuffle 3 random Skills into your draw pile. They cost 0 this combat. Exhaust.',
         root=random_cards('skill', 'DrawPile', 3), exhaust=True),
    dict(id='chrysalis+', name='Chrysalis+', cost=2, rarity='Rare', tags=['skill'],
         text='Shuffle 5 random Skills into your draw pile. They cost 0 this combat. Exhaust.',
         root=random_cards('skill', 'DrawPile', 5), exhaust=True),
    dict(id='metamorphosis', name='Metamorphosis', cost=2, rarity='Rare', tags=['skill'],
         text='Shuffle 3 random Attacks into your draw pile. They cost 0 this combat. Exhaust.',
         root=random_cards('attack', 'DrawPile', 3), exhaust=True),
    dict(id='metamorphosis+', name='Metamorphosis+', cost=2, rarity='Rare', tags=['skill'],
         text='Shuffle 5 random Attacks into your draw pile. They cost 0 this combat. Exhaust.',
         root=random_cards('attack', 'DrawPile', 5), exhaust=True),
    dict(id='jack_of_all_trades', name='Jack of All Trades', cost=0, rarity='Uncommon',
         tags=['skill'],
         text='Add 1 random Colorless card into your hand. Exhaust.',
         root=random_cards('colorless', 'Hand', 1), exhaust=True),
    dict(id='jack_of_all_trades+', name='Jack of All Trades+', cost=0, rarity='Uncommon',
         tags=['skill'],
         text='Add 2 random Colorless cards into your hand. Exhaust.',
         root=random_cards('colorless', 'Hand', 2), exhaust=True),
    dict(id='transmutation', name='Transmutation', cost=0, rarity='Rare',
         tags=['skill', 'x_cost'],
         text='Add X random Colorless cards into your hand. They cost 0 this turn. Exhaust.',
         root=random_cards('colorless', 'Hand', x_cost()), exhaust=True),
    dict(id='transmutation+', name='Transmutation+', cost=0, rarity='Rare',
         tags=['skill', 'x_cost'],
         text='Add X random Colorless cards into your hand. They cost 0 this turn. Exhaust.',
         root=random_cards('colorless', 'Hand', x_cost()), exhaust=True),
    # ---- 从抽牌堆取牌 ----
    dict(id='secret_technique', name='Secret Technique', cost=0, rarity='Rare', tags=['skill'],
         text='Put a Skill from your draw pile into your hand. Exhaust.',
         root=choose_from_draw_pile('skill'), exhaust=True),
    dict(id='secret_technique+', name='Secret Technique+', cost=0, rarity='Rare',
         tags=['skill'],
         text='Put a Skill from your draw pile into your hand.',
         root=choose_from_draw_pile('skill')),
    dict(id='secret_weapon', name='Secret Weapon', cost=0, rarity='Rare', tags=['skill'],
         text='Put an Attack from your draw pile into your hand. Exhaust.',
         root=choose_from_draw_pile('attack'), exhaust=True),
    dict(id='secret_weapon+', name='Secret Weapon+', cost=0, rarity='Rare', tags=['skill'],
         text='Put an Attack from your draw pile into your hand.',
         root=choose_from_draw_pile('attack')),
    dict(id='violence', name='Violence', cost=0, rarity='Rare', tags=['skill'],
         text='Put 3 random Attacks from your draw pile into your hand. Exhaust.',
         root=select_from_draw_pile('attack', 3), exhaust=True),
    dict(id='violence+', name='Violence+', cost=0, rarity='Rare', tags=['skill'],
         text='Put 4 random Attacks from your draw pile into your hand. Exhaust.',
         root=select_from_draw_pile('attack', 4), exhaust=True),
    # ---- 消耗手牌 ----
    dict(id='purity', name='Purity', cost=0, rarity='Uncommon', tags=['skill'],
         text='Exhaust up to 3 cards in your hand. Exhaust.',
         root=choose_exhaust_up_to(3), exhaust=True),
    dict(id='purity+', name='Purity+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Exhaust up to 5 cards in your hand. Exhaust.',
         root=choose_exhaust_up_to(5), exhaust=True),
]

# 触发器状态：`mayhem` / `magnetism` —— 都是 `TurnStarted`，都只用一个 §237/§240/§241 的载体。
STATUSES = {
    'standard.mayhem': {
        "Id": "standard.mayhem", "PackageId": "sts", "NameKey": "Mayhem",
        "DescriptionKey": "At the start of your turn, play the top card of your draw pile.",
        "Polarity": "Buff", "UsesStacks": False, "UsesDuration": False,
        "UsesCharges": False, "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff"], "PassiveModifiers": [],
        "Triggers": [{"Event": "TurnStarted",
                      "Program": {"Id": {"Value": "(unnamed)"},
                                  "Root": play_top_of_draw_pile(),
                                  "MaxNodeDepth": 64, "MaxProgramSteps": 1024}}],
    },
    'standard.magnetism': {
        "Id": "standard.magnetism", "PackageId": "sts", "NameKey": "Magnetism",
        "DescriptionKey": "At the start of your turn, add a random Colorless card into your hand.",
        "Polarity": "Buff", "UsesStacks": False, "UsesDuration": False,
        "UsesCharges": False, "StackingBehavior": "MergeWithExistingInstance",
        "Tags": ["buff"], "PassiveModifiers": [],
        "Triggers": [{"Event": "TurnStarted",
                      "Program": {"Id": {"Value": "(unnamed)"},
                                  "Root": random_cards('colorless', 'Hand', 1),
                                  "MaxNodeDepth": 64, "MaxProgramSteps": 1024}}],
    },
}

# 真·无色牌（不含 status/curse）：包含已实现的那几张与 §243 的 11 张，加上本批的。
COLORLESS = [
    'apparition', 'apparition+', 'bandage_up', 'bandage_up+', 'blind', 'dark_shackles',
    'swift_strike', 'swift_strike+',
    # §243 A 档
    'trip', 'trip+', 'panacea', 'panacea+', 'finesse', 'finesse+', 'flash_of_steel',
    'flash_of_steel+', 'good_instincts', 'good_instincts+', 'master_of_strategy',
    'master_of_strategy+', 'dramatic_entrance', 'dramatic_entrance+', 'impatience',
    'impatience+', 'deep_breath', 'deep_breath+', 'insight', 'insight+', 'miracle', 'miracle+',
    # §244 B 档
    'mayhem', 'mayhem+', 'magnetism', 'magnetism+', 'chrysalis', 'chrysalis+',
    'metamorphosis', 'metamorphosis+', 'jack_of_all_trades', 'jack_of_all_trades+',
    'transmutation', 'transmutation+', 'secret_technique', 'secret_technique+',
    'secret_weapon', 'secret_weapon+', 'violence', 'violence+', 'purity', 'purity+',
]


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}

    # ① tag
    tagged = 0
    for row in data['Cards']:
        if row['Id'] in COLORLESS:
            tags = [tag['value'] for tag in row['Tags']]
            if 'colorless' not in tags:
                row['Tags'].append({'value': 'colorless'})
                tagged += 1

    # ② 牌
    for card in CARDS:
        if card['id'] in have:
            continue
        data['Cards'].append({
            'Id': card['id'],
            'PackageId': 'sts',
            'NameKey': card['name'],
            'DescriptionKey': card['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': card['cost']}],
            'Tags': [{'value': tag} for tag in card['tags'] + ['colorless']],
            'Rarity': card['rarity'],
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': card['root'],
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {},
            'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if card.get('exhaust') else 'DiscardPile',
        })

    # ③ 状态
    statuses = {row['Id'] for row in data['Statuses']}
    for key, row in STATUSES.items():
        if key not in statuses:
            data['Statuses'].append(row)

    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards %d, statuses %d, tagged rows %d'
          % (len(data['Cards']), len(data['Statuses']), tagged))


main()
