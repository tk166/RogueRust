"""§333（内容）：`Energized` 与 `Draw Card` 两个一次性状态，并把 `snecko_eye` 迁到管线上。

wiki 语义（两个来源）：

* `Energized` —— *"Gain X additional Energy next turn."*（`Outmaneuver` 2/3、`Doppelganger` X）
* `Draw Card` —— *"Draw X additional cards next turn."*（`Doppelganger` X、`Predator` 2）

两条都是 **Intensity + 只下一回合**，所以内容就是"一条修饰器 + `one_shot_turn_start` 标签"，
不需要触发器 —— 过期由内核在抽牌之后做（§333）。

顺带修 `snecko_eye`：它的 `TurnStarted` 触发器里 `drawCards 2`（在正常抽 5 **之前**抽），
而 wiki 说 *"Draw 2 additional cards each turn"* —— 那是 `TurnStartDraw/AddFlat 2` 的语义。
改成修饰器之后，"先抽 2 再抽 5" 变成 "抽 7"，重洗时机与 `no_draw` / `draw_reduction` 的交互
也都跟着对了。
"""

import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

doc = json.load(io.open(CONTENT, encoding='utf-8'))
ids = {status['Id'] for status in doc['Statuses']}


def modifier(pipeline, operation, magnitude):
    return {
        'Pipeline': pipeline,
        'Operation': operation,
        'Magnitude': magnitude,
        'Priority': 100,
        'RestrictDamageKind': None,
        'AppliesToStatusId': None,
        'RestrictSourceCardTag': None,
        'Condition': None,
    }


def one_shot_status(status_id, name, description, pipeline, operation, magnitude):
    assert status_id not in ids, status_id
    doc['Statuses'].append({
        'Id': status_id,
        'PackageId': 'sts',
        'NameKey': name,
        'DescriptionKey': description,
        'Polarity': 'Buff',
        'UsesStacks': True,
        'UsesDuration': False,
        'UsesCharges': False,
        'StackingBehavior': 'MergeWithExistingInstance',
        # 标签是**机制**：内核按 `one_shot_turn_start` 找它们，读完之后摘掉（§333）。
        'Tags': ['buff', 'one_shot_turn_start'],
        'PassiveModifiers': [modifier(pipeline, operation, magnitude)],
        'Triggers': None,
    })
    print('%s: %s/%s %+d (one-shot)' % (status_id, pipeline, operation, magnitude))


one_shot_status(
    'standard.energized', 'Energized',
    'Gain X additional Energy next turn.',
    'TurnStartEnergy', 'AddPerStack', 1,
)
one_shot_status(
    'standard.draw_card_next_turn', 'Draw Card',
    'Draw X additional cards next turn.',
    'TurnStartDraw', 'AddPerStack', 1,
)

# ── snecko_eye：`drawCards 2` 触发器 → `TurnStartDraw/AddFlat 2` 修饰器 ─────────
eye = [status for status in doc['Statuses'] if status['Id'] == 'standard.snecko_eye'][0]
assert not eye['PassiveModifiers'], eye['PassiveModifiers']
triggers = eye['Triggers']
assert len(triggers) == 1 and triggers[0]['Event'] == 'TurnStarted'
children = triggers[0]['Program']['Root']['value']['Children']
before = len(children)
children[:] = [child for child in children if child.get('kind') != 'node.drawCards']
assert len(children) == before - 1, 'the drawCards node'
eye['PassiveModifiers'] = [modifier('TurnStartDraw', 'AddFlat', 2)]
print('standard.snecko_eye: drawCards 2 trigger -> TurnStartDraw/AddFlat 2')

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
print('content written')
