"""§385–§387 内容修正（三处，都有两个 wiki 来源）：

## §385 三哨兵：中间的从 **Beam** 起手（1+2 相位）

wiki.gg `Sentry`：*"Uses Bolt followed by Beam, repeating… **In the Elite encounter, the middle
Sentry instead uses Beam followed by Bolt.**"*
fandom `Sentry`：*"1st and 3rd sentries will always start with Bolt while the 2nd sentry will
always start with Beam."*

内核的循环是 `(round - 1) % Actions.len()`（`intent.rs::select_action` B3/B4）—— **按轮次**取，
不看"上一招"。所以三个哨兵 `Actions` 一样 ⇒ 相位全同。修法就是**把中间那只的两条动作换序**：
`[bolt, beam]` → `[beam, bolt]`。内容驱动，不动内核。

## §386 绿虱/红虱的 Bite 伤害恒为 0

`louse_green.bite` 的伤害是 `combatantCounter("roll.bite")`，而两只虱子的 `Rolls` 只定义了
`roll.curl_up` ⇒ `roll.bite` 永远是 0（玩家看到的"攻击 0"）。

wiki（三个来源一致）：Bite **5–7**，A2 起 **6–8**，开战时掷一次。

## §387 史莱姆老大：半血**分裂**，而不是半血改打 35

wiki.gg `Slime Boss`：*"When its HP is at or below 50%, it will split into 2 smaller Slimes
**with its current HP**."* + *"Split — Disappears and spawns 1 Acid Slime (L) and 1 Spike Slime (L)
with its current HP."*

旧内容有三处不对：
1. `phase_split` 的阈值是 `currentHealth <= 10`（应该是 **50% 上限**）；
2. 它召唤的是两只 **中等** 史莱姆、固定 10 血（应该是 **L 级**、各带**当前血量**）；
3. 还有一条 `IntentRules`：半血且第 2 轮起 → **slam**（把分裂彻底挡掉了）。

修法：删掉那条 slam 规则；`phase_split` 改成 `currentHealth * 100 <= maxHealth * 50`，
召唤 `acid_slime_l` + `spike_slime_l`，`Health` 取 `currentHealth`。

⚠️ **已知偏差**：原版是"血量到 50% ⇒ 当前意图**立刻**变成 Split，然后在它的回合分裂"；
我们是在**受到伤害的那一刻**就分裂（少一个回合的"预备"）。写在这里，不装作一样。
"""

import io
import json

PATH = 'tools/contentc/packages/sts/sts.roguedeck.json'
doc = json.load(io.open(PATH, encoding='utf-8'))


def eid(row):
    i = row.get('Id') if isinstance(row, dict) else row
    return i.get('Value') if isinstance(i, dict) else i


# ── §385：中间哨兵换序 ─────────────────────────────────────────────────────
changed = 0
for enc in doc['Encounters']:
    if eid(enc) != 'enc_three_sentries':
        continue
    for enemy in enc['Enemies']:
        if enemy.get('Id') == 'sentry_2':
            acts = [a['value'] for a in enemy['Actions']]
            assert acts == ['sentry.bolt', 'sentry.beam'], acts
            enemy['Actions'] = [{'value': 'sentry.beam'}, {'value': 'sentry.bolt'}]
            changed += 1
assert changed == 1, changed
print('§385 中间哨兵改为 beam 起手')

# ── §386：两只虱子补 roll.bite ─────────────────────────────────────────────
BITE_ROLLS = [
    {'Key': 'roll.bite', 'Min': 5, 'Max': 7},
    {'Key': 'roll.bite', 'Min': 6, 'Max': 8, 'AscensionMin': 2},
]
changed = 0
for monster in doc['Monsters']:
    if eid(monster) not in ('louse_green', 'louse_red'):
        continue
    rolls = monster.setdefault('Rolls', [])
    assert not any(r.get('Key') == 'roll.bite' for r in rolls), eid(monster)
    rolls.extend(BITE_ROLLS)
    changed += 1
assert changed == 2, changed
print('§386 louse_green / louse_red 补 roll.bite 5-7（A2 6-8）')

# ── §387：史莱姆老大半血分裂 ───────────────────────────────────────────────
changed = 0
for monster in doc['Monsters']:
    if eid(monster) != 'slime_boss':
        continue
    # 1. 删掉"半血改打 slam"那条规则（它把分裂挡掉了）。
    rules = monster.get('IntentRules') or []
    kept = [r for r in rules if (r.get('Action') or {}).get('value') != 'slime_boss.slam']
    assert len(kept) != len(rules), '那条 slam 规则不见了？'
    monster['IntentRules'] = kept
    # 2. `split`（死亡时分裂成两只中等）不该挂在 Boss 身上 —— 它是 L 级史莱姆的被动。
    monster['StartingStatuses'] = [
        s for s in monster.get('StartingStatuses') or []
        if (s.get('StatusDefinitionId') or {}).get('value') != 'standard.split'
    ]
    changed += 1
assert changed == 1, changed

changed = 0
for status in doc['Statuses']:
    if eid(status) != 'standard.phase_split':
        continue
    status['DescriptionKey'] = (
        'At 50% HP or less, splits into 1 Acid Slime (L) and 1 Spike Slime (L), '
        'each with its current HP. Fires once.'
    )
    trigger = status['Triggers'][0]
    root = trigger['Program']['Root']
    assert root['kind'] == 'node.conditional'
    # 条件：currentHealth * 100 <= maxHealth * 50（避免除法与取整）
    sel = {'kind': 'sel.source', 'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'}}
    root['value']['Condition'] = {
        'kind': 'compare',
        'value': {
            'Op': 'LessOrEqual',
            'Left': {'kind': 'multiply', 'value': {
                'Left': {'kind': 'currentHealth', 'value': {'Selector': sel}},
                'Right': {'kind': 'const', 'value': {'Value': 100}},
            }},
            'Right': {'kind': 'multiply', 'value': {
                'Left': {'kind': 'maxHealth', 'value': {'Selector': sel}},
                'Right': {'kind': 'const', 'value': {'Value': 50}},
            }},
        },
    }
    # 分裂：销毁自己 + 造 1 只 L 酸 + 1 只 L 尖，各带**当前血量**
    downed = {'kind': 'sel.sourceIncludingDowned', 'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'}}
    health = {'kind': 'currentHealth', 'value': {'Selector': downed}}
    root['value']['Then'] = {
        'kind': 'node.sequence',
        'value': {
            'Children': [
                {'kind': 'node.destroyCombatant', 'value': {'TargetSelector': downed}},
                {'kind': 'node.createCombatant', 'value': {
                    'DefinitionId': 'acid_slime_l', 'TeamId': 'enemy', 'Health': health}},
                {'kind': 'node.createCombatant', 'value': {
                    'DefinitionId': 'spike_slime_l', 'TeamId': 'enemy', 'Health': health}},
            ]
        },
    }
    changed += 1
assert changed == 1, changed
print('§387 slime_boss：半血（50%）分裂成 L 酸 + L 尖，各带当前血量')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n'
)
print('写回', PATH)
