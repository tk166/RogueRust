"""§242（内容）：最后三张红卡 —— spot_weakness / blood_for_blood / corruption。

wiki（`native/wiki_cards/*.txt`）：
* `spot_weakness` 1 费 Uncommon Skill —— `If the enemy intends to attack, gain (3;4) Strength.`
  ⚠️ dump 说的是 **Strength**（不是 Weak，那是别的版本）⇒ 按 dump。
  ⇒ `conditional(intent.targetIntendsAttack, applyStatus(strength, 3/4))`。
* `blood_for_blood` 4 费 Uncommon Attack（`CostPlus = 3`）——
  `Costs 1 less for every time you lose HP this combat. Deal (18;22) damage.`
  ⇒ tag `hp_loss_cost`（内核按它走 `CostStage::HpLossCount`）。
* `corruption` 3 费 Rare Power（`CostPlus = 2`）—— `Skills cost 0. Whenever you play a Skill, Exhaust it.`
  ⇒ 状态 `standard.corruption`；两条规则都在内核里键在它上面。
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


def apply_status(status, stacks):
    return node("node.applyStatus", TargetSelector=SEL_SELF,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def spot(stacks):
    return node("node.conditional",
                Condition={"kind": "intent.targetIntendsAttack", "value": {}},
                Then=apply_status("standard.strength", stacks),
                Else=None)


CARDS = [
    dict(id='spot_weakness', name='Spot Weakness',
         text='If the enemy intends to attack, gain 3 Strength.',
         cost=1, rarity='Uncommon', tags=['skill'], root=spot(3)),
    dict(id='spot_weakness+', name='Spot Weakness+',
         text='If the enemy intends to attack, gain 4 Strength.',
         cost=1, rarity='Uncommon', tags=['skill'], root=spot(4)),
    dict(id='blood_for_blood', name='Blood for Blood',
         text='Costs 1 less for each time you lose HP this combat. Deal 18 damage.',
         cost=4, rarity='Uncommon', tags=['attack', 'hp_loss_cost'], root=damage(18)),
    dict(id='blood_for_blood+', name='Blood for Blood+',
         text='Costs 1 less for each time you lose HP this combat. Deal 22 damage.',
         cost=3, rarity='Uncommon', tags=['attack', 'hp_loss_cost'], root=damage(22)),
    dict(id='corruption', name='Corruption',
         text='Skills cost 0. Whenever you play a Skill, Exhaust it.',
         cost=3, rarity='Rare', tags=['power'],
         root=apply_status('standard.corruption', 1)),
    dict(id='corruption+', name='Corruption+',
         text='Skills cost 0. Whenever you play a Skill, Exhaust it.',
         cost=2, rarity='Rare', tags=['power'],
         root=apply_status('standard.corruption', 1)),
]

CORRUPTION = {
    "Id": "standard.corruption",
    "PackageId": "sts",
    "NameKey": "Corruption",
    "DescriptionKey": "Skills cost 0. Whenever you play a Skill, Exhaust it.",
    "Polarity": "Buff",
    # 层数没有意义（是"在不在"而不是"几层"）—— 两条规则都只问 `has_status`。
    "UsesStacks": False,
    "UsesDuration": False,
    "UsesCharges": False,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["buff"],
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
            'Tags': [{'value': tag} for tag in card['tags']],
            'Rarity': card['rarity'],
            'Program': {'Id': {'Value': '(unnamed)'}, 'Root': card['root'],
                        'MaxNodeDepth': 64, 'MaxProgramSteps': 1024},
            'LifecyclePrograms': {}, 'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile', 'PlayedCardDestinationZone': 'DiscardPile',
        })
    statuses = {row['Id'] for row in data['Statuses']}
    if 'standard.corruption' not in statuses:
        data['Statuses'].append(CORRUPTION)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']), 'statuses', len(data['Statuses']))


main()
