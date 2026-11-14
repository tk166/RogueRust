"""§408 内容修正：无形永不过期（香炉/幽魂形态）+ 守护者卡在防御态。

## ① 无形（Intangible）永不过期 —— 玩家报的"香炉一直在生效、伤害始终只有 1"

`standard.intangible` 的 `UsesDuration` 是 **false**，而内核的时长衰减先问这一格
（`host::try_decrease_timed_statuses` → `status_bind::uses_duration`）。false 就整段跳过
⇒ 所有施加点写的 `DurationTurns` 都是白写。

后果正是玩家描述的两件事：
* **香炉**每 6 回合再给 1 层无形，而它永不过期 ⇒ 第 6 回合之后**一直**是无形；
* 无形把一切伤害压成 1 ⇒ "尖刺叠加、伤害始终只有 1"（配合下面的守护者 bug 就成了打不死）。

修法：`UsesDuration = true` + 所有施加点 `DurationTurns = 1`
（`apparition` / `apparition+` / `phantom_veil` 触发器 / `incense_burner` 触发器）。

⚠️ 上次（§400）只修了 7 条"这一回合"的状态，**漏了 intangible** —— 因为它所有施加点写的都是
`DurationTurns: 0`，我那次是按"写了 DurationTurns>0 但 uses=false"扫的，正好扫不到它。
教训：审计要按**语义**（wiki 说它什么时候消失）扫，不能只按"已经写了时长"扫。

## ② 守护者（The Guardian）卡在防御态 —— 玩家报的"一直加尖刺、不攻击不防御"

内容是这么设计的：
* `standard.mode_shift`：`DamageTaken` → `mode_shift_budget -= 伤害`；
* `IntentRules` 优先级 **80**：`mode_shift_budget <= 0` → `defensive_mode`；
* 优先级 **70**：`guard_mode >= 1 && guard_step == 0/1/2` → `roll_attack` / `twin_slam` / `whirlwind`；
* `defensive_mode` 写 `mode_shift_budget += 10`、`guard_mode = 1`、`guard_step = 0`；
* `roll_attack` 写 `guard_step = 1`、`twin_slam` 写 `2`、`whirlwind` 写 `guard_mode = 0` + `guard_step = 0`。

问题：**80 压过 70**，而 budget 只 `+10`、且**永不重置** ⇒ 一旦被打到 ≤0 就**每回合**都选
`defensive_mode` ⇒ 每回合 +3 尖刺、永远不打人。玩家看到的就是"一直在增强尖刺"。

wiki（`The Guardian`）：*"Mode Shift: After taking 30 damage in a **single turn**, gains 20 Block
and switches to Defensive Mode. After 3 turns, returns to Offensive Mode."*

修法三条：
1. `standard.mode_shift` 加 **TurnStarted** 触发器：`mode_shift_budget = 30`
   （"一回合内 30 点"⇒ 每回合重置；A9/A19 的 35/40 只体现在初始值，这一点记为偏差）；
2. 优先级 80 的条件加 `guard_mode == 0`（已经在防御态就不要再进）；
3. `defensive_mode` 的 `+= 10` 改成**绝对** `= 30`；
4. `whirlwind`（防御态的第 3 回合 = 退出动作）顺手把 `sharp_hide` **减 3**
   （wiki：离开防御态就没有尖刺；`modifyStatusStacks` 的 `Delta` 是相对量）。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(PATH, encoding='utf-8'))


def eid(row):
    i = row.get('Id') if isinstance(row, dict) else row
    return i.get('Value') if isinstance(i, dict) else i


SOURCE = {
    'kind': 'sel.source',
    'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'},
}

# ── ① 无形：UsesDuration + 施加点 DurationTurns 1 ─────────────────────────
touched_status = 0
for status in doc['Statuses']:
    if eid(status) == 'standard.intangible':
        assert status.get('UsesDuration') is not True
        status['UsesDuration'] = True
        touched_status += 1
assert touched_status == 1

touched_points = 0


def retime_intangible(node):
    """把每一处 `applyStatus{standard.intangible}` 的 DurationTurns 改成 1。"""
    global touched_points
    if isinstance(node, dict):
        if node.get('kind') == 'node.applyStatus':
            value = node.get('value') or {}
            if (value.get('StatusDefinitionId') or {}).get('value') == 'standard.intangible':
                if value.get('DurationTurns', 0) != 1:
                    value['DurationTurns'] = 1
                    touched_points += 1
        for child in node.values():
            retime_intangible(child)
    elif isinstance(node, list):
        for child in node:
            retime_intangible(child)


for card in doc['Cards']:
    retime_intangible(card.get('Program'))
for status in doc['Statuses']:
    retime_intangible(status.get('Triggers'))
print('① 无形：UsesDuration + %d 处施加点' % touched_points)

# ── ② 守护者：budget 每回合重置 + 进防御态要 guard_mode == 0 ──────────────
reset_trigger = {
    'Event': 'TurnStarted',
    'Program': {
        'Id': {'Value': '(unnamed)'},
        'Root': {
            'kind': 'node.setCombatantCounter',
            'value': {
                'TargetSelector': SOURCE,
                'CounterId': {'value': 'mode_shift_budget'},
                'Amount': {'kind': 'const', 'value': {'Value': 30}},
                'Relative': False,
                'ResultKey': None,
            },
        },
        'MaxNodeDepth': 64,
        'MaxProgramSteps': 1024,
    },
}

for status in doc['Statuses']:
    if eid(status) != 'standard.mode_shift':
        continue
    triggers = status.setdefault('Triggers', [])
    assert not any(t.get('Event') == 'TurnStarted' for t in triggers), '已经加过了'
    triggers.append(reset_trigger)
    print('② mode_shift: 加 TurnStarted 重置 budget=30')

# 规则 80 加 `guard_mode == 0`
for monster in doc['Monsters']:
    if eid(monster) != 'the_guardian':
        continue
    rules = monster.get('IntentRules') or []
    for rule in rules:
        if (rule.get('Action') or {}).get('value') != 'the_guardian.defensive_mode':
            continue
        cond = rule.get('Condition') or {}
        assert cond.get('kind') == 'intent.selfHasCounter'
        rule['Condition'] = {
            'kind': 'intent.allOf',
            'value': {'Conditions': [
                cond,
                {'kind': 'intent.selfHasCounter', 'value': {
                    'Counter': {'value': 'guard_mode'}, 'Op': 'Equal', 'Value': 0}},
            ]},
        }
        print('② 规则 80: 加 guard_mode == 0')

# defensive_mode 的 budget：相对 +10 → 绝对 30
for action in doc['EnemyActions']:
    if eid(action) != 'the_guardian.defensive_mode':
        continue
    s = json.dumps(action.get('Program'), ensure_ascii=False)
    assert '"CounterId": {"value": "mode_shift_budget"}, "Amount": {"kind": "const", "value": {"Value": 10}}, "Relative": true' in s
    s = s.replace(
        '"CounterId": {"value": "mode_shift_budget"}, "Amount": {"kind": "const", "value": {"Value": 10}}, "Relative": true',
        '"CounterId": {"value": "mode_shift_budget"}, "Amount": {"kind": "const", "value": {"Value": 30}}, "Relative": false',
    )
    action['Program'] = json.loads(s)
    print('② defensive_mode: budget 改成绝对 30')

# whirlwind（退出防御态）顺手把尖刺减 3
for action in doc['EnemyActions']:
    if eid(action) != 'the_guardian.whirlwind':
        continue
    children = action['Program']['Root']['value']['Children']
    assert children[-1]['kind'] == 'node.setCombatantCounter'
    children.append({
        'kind': 'node.modifyStatusStacks',
        'value': {
            'TargetSelector': SOURCE,
            'StatusDefinitionId': {'value': 'standard.sharp_hide'},
            'Delta': {'kind': 'const', 'value': {'Value': -3}},
            'ResultKey': None,
        },
    })
    print('② whirlwind: 退出防御态时 sharp_hide -3')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
)
print('写回', PATH)
