"""§400 内容修正（三条，都是玩家实机报的）：

## ① #2 "狂怒持续到下一回合" —— 同类一共 7 个状态

`DurationTurns` 写了也没用：内核的时长衰减（`host::try_decrease_timed_statuses`）先问
`status_bind::uses_duration(content, id)` —— **状态定义上的 `UsesDuration`**。
而内容里 150 条状态只有 **1 条**是 `true`（`no_block_from_cards`）⇒ 其余"这一回合"的状态
**永远不会到期**。玩家看到的"狂怒持续到下一回合"就是它。

同类审计（英文 `DescriptionKey` 里带 "this turn" / "end of your turn" 且**施加状态**的卡）：

| 卡 | 状态 | 语义 | 修法 |
|---|---|---|---|
| Rage | `standard.rage` | 本回合每次攻击给格挡 | `UsesDuration=true` + `DurationTurns=1` |
| Flex | `standard.lose_strength` | 回合结束失去力量（**不清就是每回合永久掉**） | 同上 |
| Battle Trance | `standard.no_draw` | 本回合不能再抽牌 | 同上 |
| Flame Barrier | `standard.flame_barrier` | 本回合被攻击反伤 | 同上 |
| Double Tap | `standard.double_tap` | 本回合下一次攻击打两次 | 同上 |
| Enlightenment | `standard.cap_cost_at` | 本回合手牌费用降为 1 | 同上 |
| Dark Shackles | `standard.regain_strength` | 回合结束把力量还回去 | 同上 |

**不是** bug 的（永久能力，靠 TurnEnded 触发器每回合生效）：`metallicize` / `combust` /
`omega` / `regain_strength` 之外的 power —— 它们的 `DurationTurns` 保持 0。

时序安全：turn-end 处理器 #3（触发器）**先于** #4（时长衰减）⇒ 带 1 回合时长的状态
会先触发自己的 TurnEnded 效果、再被删掉（`lose_strength` / `regain_strength` 正是这个顺序）。

## ② #6 "粘液/伤口堆积不消失、回合没正常结束"

内容里 **49 张卡**的 `TurnEndHandDestinationZone` 写成了 `"Hand"`，而内核照做
（`host::turn_end_hand_destination` 的 `Some("Hand") => CardZone::Hand`）⇒
**回合结束时那张牌留在手里**。里面既有 `slimed` / `wound` / `burn` / `injury` / `doubt` /
`writhe` 这种垃圾牌，也有 `cleave` / `bludgeon` / `twin_strike` 这种普通牌 ——
没打出去就永远留在手里，手牌越堆越满、抽牌被卡住（"一轮 turn 没有正常结束"）。

StS 里这些牌**没有一张**是 retain 的；retain 由 `RetainInHandOnTurnEnd` 这个**独立字段**
表达（内容里只有 12 张观者牌是 true）。⇒ 把 49 张的 `"Hand"` 全部改成 `"DiscardPile"`。

## ③ #5 史莱姆老大：分裂应当发生在**它的回合**，不是掉血那一刻

wiki.gg `Slime Boss`：*"Once its HP reaches 50% or lower, its current Intent will be
**immediately changed to Split**"* —— 意图立刻变，**分裂在它的回合发生**。
之前用 `standard.phase_split` 的 `DamageTaken` 触发器是"掉到 50% 立刻分裂"，
玩家看到的是"血条刚过一半就凭空变成两只"。

修法（回到"意图驱动"）：
* 新增敌人动作 `slime_boss.split`（Intent Kind `Special`，Label "Split"），
  程序：造 1 只 `acid_slime_l` + 1 只 `spike_slime_l`（`Health` = 自己的**当前**血量），
  然后销毁自己（**先造后毁** —— 先毁会让 `currentHealth` 读到 0，两只只有 1 点血）；
* 加一条 `IntentRules`：`healthPercent <= 50` ⇒ `slime_boss.split`（Priority 90，压过循环）；
* 摘掉 `standard.phase_split`（不再需要那个触发器）。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(PATH, encoding='utf-8'))


def eid(row):
    i = row.get('Id') if isinstance(row, dict) else row
    return i.get('Value') if isinstance(i, dict) else i


# ── ① 让"这一回合"的状态真的会到期 ────────────────────────────────────────
TIMED = [
    'standard.rage',
    'standard.lose_strength',
    'standard.no_draw',
    'standard.flame_barrier',
    'standard.double_tap',
    'standard.cap_cost_at',
    'standard.regain_strength',
]
touched_status = 0
for status in doc['Statuses']:
    if eid(status) in TIMED:
        assert status.get('UsesDuration') is not True, eid(status)
        status['UsesDuration'] = True
        touched_status += 1
assert touched_status == len(TIMED), touched_status

# 施加它们的地方：`DurationTurns` 0 → 1（只改这 7 个状态，别动别的）
touched_cards = 0


def retime(node):
    """递归把 `applyStatus{StatusDefinitionId in TIMED}` 的 DurationTurns 改成 1。"""
    global touched_cards
    if isinstance(node, dict):
        if node.get('kind') == 'node.applyStatus':
            value = node.get('value') or {}
            sid = (value.get('StatusDefinitionId') or {}).get('value')
            if sid in TIMED:
                if value.get('DurationTurns', 0) != 1:
                    value['DurationTurns'] = 1
                    touched_cards += 1
        for child in node.values():
            retime(child)
    elif isinstance(node, list):
        for child in node:
            retime(child)


for card in doc['Cards']:
    retime(card.get('Program'))
    retime(card.get('LifecyclePrograms'))
print('① 时长：%d 个状态 + %d 处施加点' % (touched_status, touched_cards))

# ── ② 回合结束的手牌落区：`Hand` → `DiscardPile` ──────────────────────────
retained = {eid(c) for c in doc['Cards'] if c.get('RetainInHandOnTurnEnd')}
fixed = 0
for card in doc['Cards']:
    if card.get('TurnEndHandDestinationZone') == 'Hand' and eid(card) not in retained:
        card['TurnEndHandDestinationZone'] = 'DiscardPile'
        fixed += 1
assert fixed > 0, '没有需要修的卡？'
print('② 回合结束落区：%d 张卡从 Hand 改成 DiscardPile' % fixed)

# ── ③ 史莱姆老大：意图驱动的分裂 ──────────────────────────────────────────
SPLIT_ID = 'slime_boss.split'
if not any(eid(a) == SPLIT_ID for a in doc['EnemyActions']):
    downed = {
        'kind': 'sel.sourceIncludingDowned',
        'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'},
    }
    health = {'kind': 'currentHealth', 'value': {'Selector': downed}}
    doc['EnemyActions'].append({
        'Id': SPLIT_ID,
        'PackageId': 'sts',
        'NameKey': 'Split',
        'DescriptionKey': 'Split — disappears and spawns 1 Acid Slime (L) and 1 Spike Slime (L) '
                          'with its current HP',
        'Intent': {'Kind': 'Special', 'Label': 'Split'},
        'Program': {
            'Id': {'Value': '(unnamed)'},
            'Root': {
                'kind': 'node.sequence',
                'value': {
                    'Children': [
                        # ⚠️ **先造后毁**：`currentHealth` 在求值那一刻读，先销毁会读到 0。
                        {'kind': 'node.createCombatant', 'value': {
                            'DefinitionId': 'acid_slime_l', 'TeamId': 'enemy', 'Health': health}},
                        {'kind': 'node.createCombatant', 'value': {
                            'DefinitionId': 'spike_slime_l', 'TeamId': 'enemy', 'Health': health}},
                        {'kind': 'node.destroyCombatant', 'value': {'TargetSelector': downed}},
                    ]
                },
            },
            'MaxNodeDepth': 64,
            'MaxProgramSteps': 1024,
        },
    })
    print('③ 新增敌人动作 %s' % SPLIT_ID)

SPLIT_RULE = {
    'Condition': {
        'kind': 'intent.allOf',
        'value': {'Conditions': [
            {'kind': 'intent.healthPercent', 'value': {'Op': 'LessOrEqual', 'Percent': 50}},
        ]},
    },
    'Action': {'value': SPLIT_ID},
    'Priority': 90,
}


def fix_slime_boss(entry, tag):
    """把 phase_split 换成"半血 ⇒ 意图变 Split"（encounter 内联与名册两份都要改）。"""
    if entry.get('Id') != 'slime_boss':
        return 0
    statuses = [s for s in entry.get('StartingStatuses') or []
                if (s.get('StatusDefinitionId') or {}).get('value') != 'standard.phase_split']
    rules = [r for r in entry.get('IntentRules') or []
             if (r.get('Action') or {}).get('value') != SPLIT_ID]
    entry['StartingStatuses'] = statuses
    entry['IntentRules'] = [SPLIT_RULE] + rules
    print('   %s: 摘掉 phase_split、加 Split 规则' % tag)
    return 1


count = 0
for encounter in doc['Encounters']:
    for enemy in encounter['Enemies']:
        if isinstance(enemy.get('Id'), str):
            count += fix_slime_boss(enemy, 'inline/%s' % eid(encounter))
for monster in doc['Monsters']:
    count += fix_slime_boss(monster, 'roster')
assert count == 2, count

# `phase_split` 这个状态已经没有消费者了 —— 留着会让人以为它还在生效。
doc['Statuses'] = [s for s in doc['Statuses'] if eid(s) != 'standard.phase_split']
print('③ 删除不再使用的 standard.phase_split')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
)
print('写回', PATH)
