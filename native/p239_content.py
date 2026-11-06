"""§239（内容）：`clash`（PlayCondition）与 `burning_pact`（选一张消耗 + 抽牌）。

wiki（`native/wiki_cards/*.txt`）：
* `clash` 0 费 Common Attack ——
  `Can only be played if every card in your hand is an Attack. Deal (14;18) damage.`
  ⇒ `PlayCondition` 是 **CARD 行的第 5 格**（`F_TERM`），镜像里 62/62 原本都是 `ABSENT16`；
  这是第一张真正用它 的牌。事实由 `play.rs::play_condition_validator` 算好
  （`playCondition.handIsAllAttacks`，见 `exec::PLAY_CONDITION_HAND_ALL_ATTACKS`）。
* `burning_pact` 1 费 Uncommon Skill —— `Exhaust 1 card. Draw (2;3) cards.`
  ⇒ `chooseCards{FromZone: Hand, Min 1, Max 1, Then: Exhaust}` + `draw`。
  ⚠️ wiki 的 `{{KW|Exhaust}}` 在这里是**动词**（与 §235 的 `sever_soul` 同源），
  牌本身打完进弃牌堆 —— 这条偏差记在 `card_wiki_inventory.DEVIATIONS`。
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


def damage(n):
    return node("node.dealDamage", TargetSelector=SEL_TARGET, Amount=const(n),
                IgnoresBlock=False, Element=None)


def draw(n):
    return node("node.drawCards", TargetSelector=SEL_SELF, Count=const(n))


def choose_exhaust():
    return node("node.chooseCards", OwnerSelector=SEL_SELF, FromZone="Hand",
                Min=1, Max=1, Then="Exhaust", ToZone="Hand")


def sequence(*children):
    return node("node.sequence", Children=list(children))


PLAY_CONDITION = {"kind": "event.bool", "value": {"FieldKey": "playCondition.handIsAllAttacks"}}

CARDS = [
    dict(id='clash', name='Clash',
         text='Can only be played if every card in your hand is an Attack. Deal 14 damage.',
         cost=0, rarity='Common', tags=['attack'], play_condition=PLAY_CONDITION,
         root=damage(14)),
    dict(id='clash+', name='Clash+',
         text='Can only be played if every card in your hand is an Attack. Deal 18 damage.',
         cost=0, rarity='Common', tags=['attack'], play_condition=PLAY_CONDITION,
         root=damage(18)),
    dict(id='burning_pact', name='Burning Pact',
         text='Exhaust 1 card. Draw 2 cards.',
         cost=1, rarity='Uncommon', tags=['skill'],
         root=sequence(choose_exhaust(), draw(2))),
    dict(id='burning_pact+', name='Burning Pact+',
         text='Exhaust 1 card. Draw 3 cards.',
         cost=1, rarity='Uncommon', tags=['skill'],
         root=sequence(choose_exhaust(), draw(3))),
]


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}
    for card in CARDS:
        if card['id'] in have:
            continue
        row = {
            'Id': card['id'],
            'PackageId': 'sts',
            'NameKey': card['name'],
            'DescriptionKey': card['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': card['cost']}],
            'Tags': [{'value': tag} for tag in card['tags']],
            'Rarity': card['rarity'],
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': card['root'],
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {},
            'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'DiscardPile',
        }
        if card.get('play_condition') is not None:
            row['PlayCondition'] = card['play_condition']
        data['Cards'].append(row)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']))


main()
