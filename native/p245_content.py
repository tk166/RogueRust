"""§245（内容）：无色「既有载体」组的第一批 —— apotheosis / thinking_ahead / panic_button。

数字来自 `native/wiki_cards/<id>.txt`（§243 抓的 dump）：
* `apotheosis` 2/1 Rare Skill —— `Upgrade ALL your cards for the rest of combat. Exhaust.`
  ⇒ `node.upgradeCards{OwnerSelector: sel.source}`（**不给 FromZone = 走全部牌区**，§227 起就是这样）
* `thinking_ahead` 0 Rare Skill —— `Draw 2 cards. Put a card from your hand on top of your
  draw pile. Exhaust.`（升级去掉 Exhaust）⇒ `sequence[drawCards(2), chooseCards{Then: ToDrawPileTop}]`
* `panic_button` 0 Uncommon Skill —— `Gain (30;40) Block. You cannot gain Block from cards for
  2 turns. Exhaust.` ⇒ `sequence[gainBlock, applyStatus(standard.no_block_from_cards, dur 2)]`
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def sequence(*children):
    return node("node.sequence", Children=list(children))


def block(amount):
    return node("node.gainBlock", TargetSelector=SEL_SELF, Amount=const(amount))


def draw(count):
    return node("node.drawCards", TargetSelector=SEL_SELF, Count=const(count))


def upgrade_all():
    # 不给 `FromZone` ⇒ 全部牌区（§227）。
    return node("node.upgradeCards", OwnerSelector=SEL_SELF)


def put_one_on_top():
    return node("node.chooseCards", OwnerSelector=SEL_SELF, FromZone="Hand",
                Min=1, Max=1, Then="ToDrawPileTop", ToZone="Hand")


def apply_status(status, stacks, duration=0):
    return node("node.applyStatus", TargetSelector=SEL_SELF,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=duration, Charges=0)


CARDS = [
    dict(id='apotheosis', name='Apotheosis', cost=2, rarity='Rare', tags=['skill'],
         text='Upgrade ALL your cards for the rest of combat. Exhaust.',
         root=upgrade_all(), exhaust=True),
    dict(id='apotheosis+', name='Apotheosis+', cost=1, rarity='Rare', tags=['skill'],
         text='Upgrade ALL your cards for the rest of combat. Exhaust.',
         root=upgrade_all(), exhaust=True),
    dict(id='thinking_ahead', name='Thinking Ahead', cost=0, rarity='Rare', tags=['skill'],
         text='Draw 2 cards. Put a card from your hand on top of your draw pile. Exhaust.',
         root=sequence(draw(2), put_one_on_top()), exhaust=True),
    dict(id='thinking_ahead+', name='Thinking Ahead+', cost=0, rarity='Rare', tags=['skill'],
         text='Draw 2 cards. Put a card from your hand on top of your draw pile.',
         root=sequence(draw(2), put_one_on_top())),
    dict(id='panic_button', name='Panic Button', cost=0, rarity='Uncommon', tags=['skill'],
         text='Gain 30 Block. You cannot gain Block from cards for 2 turns. Exhaust.',
         root=sequence(block(30),
                       apply_status('standard.no_block_from_cards', 1, duration=2)),
         exhaust=True),
    dict(id='panic_button+', name='Panic Button+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Gain 40 Block. You cannot gain Block from cards for 2 turns. Exhaust.',
         root=sequence(block(40),
                       apply_status('standard.no_block_from_cards', 1, duration=2)),
         exhaust=True),
]

NO_BLOCK = {
    "Id": "standard.no_block_from_cards",
    "PackageId": "sts",
    "NameKey": "No Block From Cards",
    "DescriptionKey": "You cannot gain Block from cards.",
    "Polarity": "Debuff",
    "UsesStacks": False,
    "UsesDuration": True,
    "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["debuff"],
    "PassiveModifiers": [],
    "Triggers": [],
}


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}
    for card in CARDS:
        if card['id'] in have:
            continue
        data['Cards'].append({
            'Id': card['id'], 'PackageId': 'sts', 'NameKey': card['name'],
            'DescriptionKey': card['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': card['cost']}],
            'Tags': [{'value': tag} for tag in card['tags'] + ['colorless']],
            'Rarity': card['rarity'],
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': card['root'],
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if card.get('exhaust') else 'DiscardPile',
        })
    statuses = {row['Id'] for row in data['Statuses']}
    if 'standard.no_block_from_cards' not in statuses:
        data['Statuses'].append(NO_BLOCK)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards %d, statuses %d' % (len(data['Cards']), len(data['Statuses'])))


main()
