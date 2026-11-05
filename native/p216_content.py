"""§216 content: `Slow` becomes a marker status (the counter is the kernel's), `Nom Nom` reads rounds."""
import io
import json

SRC = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(SRC, encoding='utf-8'))

statuses = {s['Id']: s for s in doc['Statuses']}
slow = statuses['standard.slow']
assert slow['PassiveModifiers'][0]['Operation'] == 'ScalePercentPerStack', slow['PassiveModifiers']
slow['PassiveModifiers'][0]['Operation'] = 'ScalePercentPerCardPlayedThisTurn'
assert len(slow['Triggers']) == 1, slow['Triggers']
slow['Triggers'] = []
slow['StackingBehavior'] = 'MergeWithExistingInstance'
slow['Note'] = (
    '§216：标记状态 —— 计数在**内核**（`state.cards_played_this_turn`，每回合清零），不在层数。'
    'wiki: "For every card you have played this turn … Slow resets at end of turn". '
    '层数因此不参与算术（挂 1 层只是"这个能力在身上"）。'
)

# `Nom Nom`: 5 × ceil(第几轮 / 2)。wiki 写 "Current turn, divided by two (rounded up)"，而 StS 的
# `turns_played` 是玩家回合数（= 轮）；内核的 `turnNumber` 是**一轮内的行动者序号**（绕回置 1），
# 单怪场景恒为 2 ⇒ 永远 1 击。
swapped = 0


def walk(node):
    global swapped
    if isinstance(node, dict):
        if node.get('kind') == 'turnNumber':
            node['kind'] = 'roundNumber'
            swapped += 1
        for value in node.values():
            walk(value)
    elif isinstance(node, list):
        for value in node:
            walk(value)


for action in doc['EnemyActions']:
    if action['Id'].split('.')[0] == 'maw':
        walk(action.get('Program'))
        walk(action.get('ProgramAsc'))
assert swapped == 1, swapped

json.dump(doc, io.open(SRC, 'w', encoding='utf-8', newline='\n'), ensure_ascii=False, indent=2)
open(SRC, 'a', encoding='utf-8').write('\n')
print('content patched: slow marker + nom_nom reads rounds (%d swap)' % swapped)
