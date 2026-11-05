"""§219: `Dark Shackles` needs the **mirror** of `lose_strength`.

The card said `dealStatus(standard.strength, -9)`, and the kernel refuses negative stacks on
application (`exec.rs:4063`, copied from `StatusEffects.cs:55-62`), so **playing it was
`Effect(Modifier)`** -- another latent landmine that no test had stepped on.

wiki: *"Enemy loses 9 (15) Strength **this turn**."* So the shape is "reduce now, give it back at the
end of the turn" = the mirror image of `lose_strength` (which subtracts at turn end). `modifyStatusStacks`
clamps at 0 (reference `:860-865`), so reducing an enemy that has less than 9 Strength stops at 0 --
that is the reference's own answer and is declared in the inventory.
"""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))

statuses = {status['Id']: status for status in doc['Statuses']}
if 'standard.regain_strength' not in statuses:
    source = statuses['standard.lose_strength']
    mirror = json.loads(json.dumps(source))          # deep copy, then flip the two signs
    mirror['Id'] = 'standard.regain_strength'
    mirror['NameKey'] = 'Regain Strength'
    mirror['DescriptionKey'] = (
        'At the end of the turn, regain Strength equal to this status\'s stacks, then remove it.')
    mirror['Polarity'] = 'Buff'
    mirror['Tags'] = ['buff']
    kids = mirror['Triggers'][0]['Program']['Root']['value']['Children']
    # children[0]: gain `ownStacks` strength（原来是 `0 - ownStacks`）
    kids[0]['value']['Delta'] = {
        'kind': 'add',
        'value': {
            'Left': {'kind': 'const', 'value': {'Value': 0}},
            'Right': {
                'kind': 'combatantStatusStacks',
                'value': {
                    'Selector': {'kind': 'sel.source',
                                 'value': {'Cardinality': 'ZeroOrOne',
                                           'RequiredContextCapabilities': 'Source'}},
                    'StatusId': {'value': 'standard.regain_strength'},
                },
            },
        },
    }
    # children[1]: 清掉自己（照 lose_strength 的写法，把 id 换掉）
    kids[1]['value']['StatusDefinitionId'] = {'value': 'standard.regain_strength'}
    kids[1]['value']['Delta'] = {
        'kind': 'subtract',
        'value': {
            'Left': {'kind': 'const', 'value': {'Value': 0}},
            'Right': {
                'kind': 'combatantStatusStacks',
                'value': {
                    'Selector': {'kind': 'sel.source',
                                 'value': {'Cardinality': 'ZeroOrOne',
                                           'RequiredContextCapabilities': 'Source'}},
                    'StatusId': {'value': 'standard.regain_strength'},
                },
            },
        },
    }
    # 插在有顺序意义的表里：紧跟 lose_dexterity 之后（保持“一对镜像”挨着）
    position = [index for index, status in enumerate(doc['Statuses'])
                if status['Id'] == 'standard.lose_dexterity']
    assert position, 'lose_dexterity must exist'
    doc['Statuses'].insert(position[0] + 1, mirror)
    print('added status standard.regain_strength')

for card_id in ('dark_shackles', 'dark_shackles+'):
    card = next((entry for entry in doc['Cards'] if entry['Id'] == card_id), None)
    if card is None:
        continue
    stacks = 9 if card_id == 'dark_shackles' else 15
    card['Program']['Root'] = {
        'kind': 'node.sequence',
        'value': {'Children': [
            # 立刻降力量（钳在 0，参考行为）
            {
                'kind': 'node.modifyStatusStacks',
                'value': {
                    'TargetSelector': {'kind': 'sel.eventTarget',
                                       'value': {'Cardinality': 'ZeroOrOne',
                                                 'RequiredContextCapabilities': 'EventTarget'}},
                    'StatusDefinitionId': {'value': 'standard.strength'},
                    'Delta': {'kind': 'const', 'value': {'Value': -stacks}},
                    'ResultKey': None,
                },
            },
            # 回合末还回去
            {
                'kind': 'node.applyStatus',
                'value': {
                    'TargetSelector': {'kind': 'sel.eventTarget',
                                       'value': {'Cardinality': 'ZeroOrOne',
                                                 'RequiredContextCapabilities': 'EventTarget'}},
                    'StatusDefinitionId': {'value': 'standard.regain_strength'},
                    'Stacks': {'kind': 'const', 'value': {'Value': stacks}},
                    'DurationTurns': 0,
                    'Charges': 0,
                    'ResultKey': None,
                },
            },
        ]},
    }
    print('rewrote %s: -%d strength now, +%d back at turn end' % (card_id, stacks, stacks))

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('content patched')
