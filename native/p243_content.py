"""§243（内容）：无色 A 档 —— 11 张，全部是"0 费工具牌"形状。

数字全部抄自 `native/wiki_cards/<id>.txt`（§243 那一批 dump，源头是
`slaythespire.wiki.gg/wiki/Module:Cards/data`）：

| 牌 | 费用 | 原文 |
|---|---|---|
| `trip`            | 0 | Apply 2 Vulnerable to the target. (升级：to ALL enemies.) |
| `panacea`         | 0 | Gain (1;2) Artifact. Exhaust. |
| `finesse`         | 0 | Gain (2;4) Block. Draw 1 card. |
| `flash_of_steel`  | 0 | Deal (3;6) damage. Draw 1 card. |
| `good_instincts`  | 0 | Gain (6;9) Block. |
| `master_of_strategy` | 0 | Draw (3;4) cards. Exhaust. |
| `dramatic_entrance` | 0 | Innate. Deal (8;12) damage to ALL enemies. Exhaust. |
| `impatience`      | 0 | If you have no Attacks in your hand, draw (2;3) cards. |
| `deep_breath`     | 0 | Shuffle your discard pile into your draw pile. Draw (1;2 cards). |
| `insight`         | 0 | **Special**：Retain. Draw (2;3) cards. Exhaust. |
| `miracle`         | 0 | **Special**：Retain. Gain (1;2) Energy. Exhaust. |

`impatience` 与 `deep_breath` 各要一个小载体（`hand.hasCardWithTag` / `shuffleDiscardIntoDraw`），
其余 **9 张内核零改动**。
"""
import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
SEL_SELF = {"kind": "sel.source",
            "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
SEL_TARGET = {"kind": "sel.eventTarget",
              "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}
SEL_ALL_ENEMIES = {"kind": "sel.allEnemies",
                   "value": {"Cardinality": "Any", "RequiredContextCapabilities": "Source"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def sequence(*children):
    return node("node.sequence", Children=list(children))


def block(amount, target=SEL_SELF):
    return node("node.gainBlock", TargetSelector=target, Amount=const(amount))


def damage(amount, target=SEL_TARGET):
    return node("node.dealDamage", TargetSelector=target, Amount=const(amount),
                IgnoresBlock=False, Element=None)


def apply_status(status, stacks, target=SEL_SELF):
    return node("node.applyStatus", TargetSelector=target,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def draw(count):
    return node("node.drawCards", TargetSelector=SEL_SELF, Count=const(count))


def energy(amount):
    return node("node.gainResource", Amount=const(amount),
                ResourceId="standard.energy", TargetSelector=SEL_SELF)


def shuffle_discard():
    return node("node.shuffleDiscardIntoDraw", OwnerSelector=SEL_SELF)


def hand_has_attack():
    return {"kind": "hand.hasCardWithTag", "value": {"Tag": "attack"}}


def conditional(condition, then, otherwise=None):
    return node("node.conditional", Condition=condition, Then=then, Else=otherwise)


CARDS = [
    # ---- 纯伤害/格挡/状态 ----
    dict(id='trip', name='Trip', cost=0, rarity='Uncommon', tags=['skill'],
         text='Apply 2 Vulnerable to the target.',
         root=apply_status('standard.vulnerable', 2, SEL_TARGET)),
    dict(id='trip+', name='Trip+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Apply 2 Vulnerable to ALL enemies.',
         root=apply_status('standard.vulnerable', 2, SEL_ALL_ENEMIES)),
    dict(id='panacea', name='Panacea', cost=0, rarity='Uncommon', tags=['skill'],
         text='Gain 1 Artifact. Exhaust.',
         root=apply_status('standard.artifact', 1), exhaust=True),
    dict(id='panacea+', name='Panacea+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Gain 2 Artifact. Exhaust.',
         root=apply_status('standard.artifact', 2), exhaust=True),
    dict(id='finesse', name='Finesse', cost=0, rarity='Uncommon', tags=['skill'],
         text='Gain 2 Block. Draw 1 card.', root=sequence(block(2), draw(1))),
    dict(id='finesse+', name='Finesse+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Gain 4 Block. Draw 1 card.', root=sequence(block(4), draw(1))),
    dict(id='flash_of_steel', name='Flash of Steel', cost=0, rarity='Uncommon',
         tags=['attack'], text='Deal 3 damage. Draw 1 card.',
         root=sequence(damage(3), draw(1))),
    dict(id='flash_of_steel+', name='Flash of Steel+', cost=0, rarity='Uncommon',
         tags=['attack'], text='Deal 6 damage. Draw 1 card.',
         root=sequence(damage(6), draw(1))),
    dict(id='good_instincts', name='Good Instincts', cost=0, rarity='Uncommon',
         tags=['skill'], text='Gain 6 Block.', root=block(6)),
    dict(id='good_instincts+', name='Good Instincts+', cost=0, rarity='Uncommon',
         tags=['skill'], text='Gain 9 Block.', root=block(9)),
    dict(id='master_of_strategy', name='Master of Strategy', cost=0, rarity='Rare',
         tags=['skill'], text='Draw 3 cards. Exhaust.', root=draw(3), exhaust=True),
    dict(id='master_of_strategy+', name='Master of Strategy+', cost=0, rarity='Rare',
         tags=['skill'], text='Draw 4 cards. Exhaust.', root=draw(4), exhaust=True),
    dict(id='dramatic_entrance', name='Dramatic Entrance', cost=0, rarity='Uncommon',
         tags=['attack', 'innate'],
         text='Innate. Deal 8 damage to ALL enemies. Exhaust.',
         root=damage(8, SEL_ALL_ENEMIES), exhaust=True),
    dict(id='dramatic_entrance+', name='Dramatic Entrance+', cost=0, rarity='Uncommon',
         tags=['attack', 'innate'],
         text='Innate. Deal 12 damage to ALL enemies. Exhaust.',
         root=damage(12, SEL_ALL_ENEMIES), exhaust=True),
    # ---- 条件抽牌 / 重洗 ----
    dict(id='impatience', name='Impatience', cost=0, rarity='Uncommon', tags=['skill'],
         text='If you have no Attacks in your hand, draw 2 cards.',
         root=conditional({"kind": "not", "value": {"Condition": hand_has_attack()}}, draw(2))),
    dict(id='impatience+', name='Impatience+', cost=0, rarity='Uncommon', tags=['skill'],
         text='If you have no Attacks in your hand, draw 3 cards.',
         root=conditional({"kind": "not", "value": {"Condition": hand_has_attack()}}, draw(3))),
    dict(id='deep_breath', name='Deep Breath', cost=0, rarity='Uncommon', tags=['skill'],
         text='Shuffle your discard pile into your draw pile. Draw 1 card.',
         root=sequence(shuffle_discard(), draw(1))),
    dict(id='deep_breath+', name='Deep Breath+', cost=0, rarity='Uncommon', tags=['skill'],
         text='Shuffle your discard pile into your draw pile. Draw 2 cards.',
         root=sequence(shuffle_discard(), draw(2))),
    # ---- Special（由别的牌/遗物生成） ----
    dict(id='insight', name='Insight', cost=0, rarity='Special', tags=['skill'],
         text='Retain. Draw 2 cards. Exhaust.', retain=True,
         root=draw(2), exhaust=True),
    dict(id='insight+', name='Insight+', cost=0, rarity='Special', tags=['skill'],
         text='Retain. Draw 3 cards. Exhaust.', retain=True,
         root=draw(3), exhaust=True),
    dict(id='miracle', name='Miracle', cost=0, rarity='Special', tags=['skill'],
         text='Retain. Gain 1 Energy. Exhaust.', retain=True,
         root=energy(1), exhaust=True),
    dict(id='miracle+', name='Miracle+', cost=0, rarity='Special', tags=['skill'],
         text='Retain. Gain 2 Energy. Exhaust.', retain=True,
         root=energy(2), exhaust=True),
]


def main():
    data = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in data['Cards']}
    assert not (have & {card['id'] for card in CARDS}), 'already patched'
    for card in CARDS:
        data['Cards'].append({
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
            # §243：`Retain` 就是这一格（`insight` / `miracle` 是前两张 retain 牌）。
            'RetainInHandOnTurnEnd': bool(card.get('retain')),
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if card.get('exhaust') else 'DiscardPile',
        })
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']))


main()
