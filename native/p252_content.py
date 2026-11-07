"""§252（内容）：剩下 6 张 —— `through_violence` / `j.a.x.` / `safety` /
`become_almighty` / `live_forever` / `fame_and_fortune`。

牌面（wiki 正文；后三张是 `Wish` 的三个选项，所以都是**不可打出**的特殊牌）：

| 牌 | 费 | 正文 | 升级 |
|---|---|---|---|
| `through_violence` | 0 | **Retain.** Deal 20 damage. Exhaust. | 30 |
| `j.a.x.` | 0 | Lose 3 HP. Gain 2 Strength. | Strength 3（**不 Exhaust** —— wiki 补丁记录「No longer exhausts」） |
| `safety` | 1 | **Retain.** Gain 12 Block. Exhaust. | 16 |
| `become_almighty` | 不可打出（Power） | Gain 3 Strength. | 4 |
| `live_forever` | 不可打出（Power） | Gain 6 Plated Armor. | 8 |
| `fame_and_fortune` | 不可打出（Skill） | Gain 25 Gold. | 30 |

**零内核改动**：`loseHp` / `applyStatus` / `gainBlock` / `gainGold`（§250）都在手边。

三处说明：

1. `become_almighty` / `live_forever` / `fame_and_fortune` 在 StS 里「只能由 `Wish` 造出来并
   **由它打出**」—— 所以它们的 `Program` 是**真的会跑**的（`Wish` 用出牌通道打它），
   只是玩家在手上打不出（`unplayable` tag）。这与 `void`/`burn` 那些"打不出、效果靠触发器"的
   牌不是一回事：这条路上"打得出"的是**别的牌**。
   `Wish` 本身是观者牌、不在范围 ⇒ 今天没有内容会打出它们，但节目与数值是对的，
   等 `Wish` 来了就能直接用（这也正是为什么写它而不是留空）。
2. `j.a.x.` 的 HP 代价走 `node.loseHp`（与 `bloodletting`/`offering` 同一格），
   **不是**费用资源：它要能被 `Rupture` 看见（wiki 的 Synergies 第一条就是 "trigger Rupture"）。
3. `fame_and_fortune` 的金币走 §250 的 `node.gainGold` —— 战斗里赚的钱在 `fight_end` 加进运行层。
   它在**本场战斗内**看起来什么都没做，那正是 wiki 说的 "does nothing for the current fight —
   it funds the run instead"。
"""
import io
import json

CONTENT = 'D:/Vibe/sts-tui/tools/contentc/packages/sts/sts.roguedeck.json'

SELF = {"kind": "sel.source",
        "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "Source"}}
TARGET = {"kind": "sel.eventTarget",
          "value": {"Cardinality": "ZeroOrOne", "RequiredContextCapabilities": "EventTarget"}}


def node(kind, **value):
    value.setdefault("ResultKey", None)
    return {"kind": kind, "value": value}


def const(n):
    return {"kind": "const", "value": {"Value": n}}


def program(root):
    return {"Id": {"Value": "(unnamed)"}, "Root": root,
            "MaxNodeDepth": 64, "MaxProgramSteps": 1024}


def seq(*children):
    return node("node.sequence", Children=list(children))


def deal_damage(amount):
    return node("node.dealDamage", TargetSelector=TARGET, Amount=amount,
                IgnoresBlock=False, Element=None)


def gain_block(amount):
    return node("node.gainBlock", TargetSelector=SELF, Amount=amount)


def lose_hp(amount):
    return node("node.loseHp", TargetSelector=SELF, Amount=amount)


def apply_status(status_id, stacks):
    return node("node.applyStatus", TargetSelector=SELF,
                StatusDefinitionId={"value": status_id}, Stacks=stacks,
                DurationTurns=0, Charges=0)


def gain_gold(amount):
    return node("node.gainGold", Amount=amount)


CARDS = [
    # ---- through_violence：与 smite 同形，只是 0 费、20/30 ----
    dict(id='through_violence', cost=0, rarity='Special', tags=['attack', 'colorless'],
         text='Retain. Deal 20 damage. Exhaust.', root=deal_damage(const(20)),
         exhaust=True, retain=True),
    dict(id='through_violence+', cost=0, rarity='Special', tags=['attack', 'colorless'],
         text='Retain. Deal 30 damage. Exhaust.', root=deal_damage(const(30)),
         exhaust=True, retain=True),
    # ---- j.a.x.：HP 代价 + 力量；**不 Exhaust** ----
    dict(id='j.a.x.', cost=0, rarity='Special', tags=['skill', 'colorless'],
         text='Lose 3 HP. Gain 2 Strength.',
         root=seq(lose_hp(const(3)), apply_status('standard.strength', const(2)))),
    dict(id='j.a.x.+', cost=0, rarity='Special', tags=['skill', 'colorless'],
         text='Lose 3 HP. Gain 3 Strength.',
         root=seq(lose_hp(const(3)), apply_status('standard.strength', const(3)))),
    # ---- safety：Retain + 格挡 + Exhaust ----
    dict(id='safety', cost=1, rarity='Special', tags=['skill', 'colorless'],
         text='Retain. Gain 12 Block. Exhaust.', root=gain_block(const(12)),
         exhaust=True, retain=True),
    dict(id='safety+', cost=1, rarity='Special', tags=['skill', 'colorless'],
         text='Retain. Gain 16 Block. Exhaust.', root=gain_block(const(16)),
         exhaust=True, retain=True),
    # ---- Wish 的三个选项：不可打出，但节目是真的（由 Wish 打出）----
    dict(id='become_almighty', cost=1, rarity='Special',
         tags=['power', 'colorless', 'unplayable'],
         text='Gain 3 Strength.', root=apply_status('standard.strength', const(3))),
    dict(id='become_almighty+', cost=1, rarity='Special',
         tags=['power', 'colorless', 'unplayable'],
         text='Gain 4 Strength.', root=apply_status('standard.strength', const(4))),
    dict(id='live_forever', cost=1, rarity='Special',
         tags=['power', 'colorless', 'unplayable'],
         text='Gain 6 Plated Armor.', root=apply_status('standard.plated_armor', const(6))),
    dict(id='live_forever+', cost=1, rarity='Special',
         tags=['power', 'colorless', 'unplayable'],
         text='Gain 8 Plated Armor.', root=apply_status('standard.plated_armor', const(8))),
    dict(id='fame_and_fortune', cost=1, rarity='Special',
         tags=['skill', 'colorless', 'unplayable'],
         text='Gain 25 Gold.', root=gain_gold(const(25))),
    dict(id='fame_and_fortune+', cost=1, rarity='Special',
         tags=['skill', 'colorless', 'unplayable'],
         text='Gain 30 Gold.', root=gain_gold(const(30))),
]


def main():
    doc = json.loads(io.open(CONTENT, encoding='utf-8').read())
    have = {row['Id'] for row in doc['Cards']}
    added = 0
    for spec in CARDS:
        if spec['id'] in have:
            continue
        doc['Cards'].append({
            'Id': spec['id'],
            'PackageId': 'sts',
            'NameKey': spec['id'],
            'DescriptionKey': spec['text'],
            'Costs': [{'ResourceId': {'value': 'standard.energy'}, 'Amount': spec['cost']}],
            'Tags': [{'value': tag} for tag in spec['tags']],
            'Rarity': spec['rarity'],
            'Program': program(spec['root']),
            'LifecyclePrograms': {},
            'RetainInHandOnTurnEnd': bool(spec.get('retain')),
            'TurnEndHandDestinationZone': 'DiscardPile',
            'PlayedCardDestinationZone': 'ExhaustPile' if spec.get('exhaust') else 'DiscardPile',
        })
        added += 1
    io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
    print('added %d row(s); cards now %d' % (added, len(doc['Cards'])))


main()
