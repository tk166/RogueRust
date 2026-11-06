"""§238（内容）：4 张牌 —— heavy_blade / feed / double_tap / exhume。

wiki（`native/wiki_cards/*.txt`）：
* `heavy_blade` 2 费 Common Attack —— `Deal 14 damage. Strength affects this card (3;5) times.`
  ⇒ 升级改的是**力量倍率**（3→5），伤害仍是 14。于是增量 = `(mult-1) × 力量`：
  伤害管线本来就会再加一次力量，所以 14 + 2×str / 14 + 4×str 得到 3×/5× 的效果。
  **内核零改动**（`multiply` + `combatantStatusStacks` 就够）。
* `feed` 1 费 Rare Attack —— `Deal (10;12) damage. If Fatal, raise your Max HP by (3;4). Exhaust.`
  ⇒ "If Fatal" 就是"打完看一眼目标还活着没有"：`compare(currentHealth(目标), 0, LessOrEqual)`；
  抬上限用新节点 `node.gainMaxHealth`（§238 内核）。
* `double_tap` 1 费 Rare Skill —— `This turn, your next (Attack is;2 Attacks are) played twice.`
  ⇒ 层数 = 次数（1/2），复制的作用域是 **Attack**（§238 的 `DUPLICATION_SCOPES`）。
* `exhume` 1 费 Rare Skill（`CostPlus = 0`）—— `Put a card from your Exhaust pile into your hand. Exhaust.`
  ⇒ `chooseCards{FromZone: ExhaustPile, Then: ToHand}`（§238 加了消耗堆来源）。
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


def strength():
    return {"kind": "combatantStatusStacks",
            "value": {"Selector": SEL_SELF, "StatusId": {"value": "standard.strength"}}}


def multiply(left, right):
    return {"kind": "multiply", "value": {"Left": left, "Right": right}}


def add(left, right):
    return {"kind": "add", "value": {"Left": left, "Right": right}}


def target_health():
    return {"kind": "currentHealth", "value": {"Selector": SEL_TARGET}}


def compare(left, right, op):
    return {"kind": "compare", "value": {"Left": left, "Right": right, "Op": op}}


def sequence(*children):
    return node("node.sequence", Children=list(children))


def damage(amount, target=SEL_TARGET):
    return node("node.dealDamage", TargetSelector=target, Amount=amount,
                IgnoresBlock=False, Element=None)


def apply_status(status, stacks):
    return node("node.applyStatus", TargetSelector=SEL_SELF,
                StatusDefinitionId={"value": status}, Stacks=const(stacks),
                DurationTurns=0, Charges=0)


def conditional(condition, then, otherwise=None):
    return node("node.conditional", Condition=condition, Then=then, Else=otherwise)


def gain_max_health(amount):
    return node("node.gainMaxHealth", TargetSelector=SEL_SELF, Amount=const(amount))


def choose_from_exhaust():
    return node("node.chooseCards", OwnerSelector=SEL_SELF, FromZone="ExhaustPile",
                Min=1, Max=1, Then="ToHand", ToZone="Hand")


def heavy_blade(mult):
    """`14 + (mult-1) × 力量` —— 管线自己还会再加一次力量。"""
    return damage(add(const(14), multiply(const(mult - 1), strength())))


CARDS = [
    dict(id='heavy_blade', name='Heavy Blade',
         text='Deal 14 damage. Strength affects this card 3 times.',
         cost=2, rarity='Common', tags=['attack'],
         root=heavy_blade(3)),
    dict(id='heavy_blade+', name='Heavy Blade+',
         text='Deal 14 damage. Strength affects this card 5 times.',
         cost=2, rarity='Common', tags=['attack'],
         root=heavy_blade(5)),
    dict(id='feed', name='Feed',
         text='Deal 10 damage. If Fatal, raise your Max HP by 3. Exhaust.',
         cost=1, rarity='Rare', tags=['attack'], exhaust=True,
         root=sequence(damage(const(10)),
                       conditional(compare(target_health(), const(0), "LessOrEqual"),
                                   gain_max_health(3)))),
    dict(id='feed+', name='Feed+',
         text='Deal 12 damage. If Fatal, raise your Max HP by 4. Exhaust.',
         cost=1, rarity='Rare', tags=['attack'], exhaust=True,
         root=sequence(damage(const(12)),
                       conditional(compare(target_health(), const(0), "LessOrEqual"),
                                   gain_max_health(4)))),
    dict(id='double_tap', name='Double Tap',
         text='This turn, your next Attack is played twice.',
         cost=1, rarity='Rare', tags=['skill'],
         root=apply_status('standard.double_tap', 1)),
    dict(id='double_tap+', name='Double Tap+',
         text='This turn, your next 2 Attacks are played twice.',
         cost=1, rarity='Rare', tags=['skill'],
         root=apply_status('standard.double_tap', 2)),
    dict(id='exhume', name='Exhume',
         text='Put a card from your Exhaust pile into your hand. Exhaust.',
         cost=1, rarity='Rare', tags=['skill'], exhaust=True,
         root=choose_from_exhaust()),
    dict(id='exhume+', name='Exhume+',
         text='Put a card from your Exhaust pile into your hand. Exhaust.',
         cost=0, rarity='Rare', tags=['skill'], exhaust=True,
         root=choose_from_exhaust()),
]

DOUBLE_TAP = {
    "Id": "standard.double_tap",
    "PackageId": "sts",
    "NameKey": "Double Tap",
    "DescriptionKey": "Your next Attack this turn is played twice.",
    "Polarity": "Buff",
    "UsesStacks": True,
    "UsesDuration": False,
    "UsesCharges": True,
    "StackingBehavior": "MergeWithExistingInstance",
    "Tags": ["buff"],
    "PassiveModifiers": [],
    "Triggers": [],
}


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
            'RetainInHandOnTurnEnd': False,
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if card.get('exhaust') else 'DiscardPile',
        })
    statuses = {row['Id'] for row in data['Statuses']}
    assert 'standard.double_tap' not in statuses
    data['Statuses'].append(DOUBLE_TAP)
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print('cards', len(data['Cards']), 'statuses', len(data['Statuses']))


main()
