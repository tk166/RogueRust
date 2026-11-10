"""§330：The Champ 二阶段**每回合都 Execute** —— 一个由文档审计挖出来的真 bug。

wiki（`native/wiki_asc/the_champ.txt`）：

> After using Anger he will use Execute the turn after.
> He will then repeat this pattern for the rest of combat: Random Move / Random Move / Execute.

内容原来的做法：`anger` 把 `champ_exec` 置 0，规则是 `champ_phase >= 1 && champ_exec <= 0`
⇒ Execute，而 **`the_champ.execute` 从不回写 `champ_exec`** ⇒ 二阶段每一回合都命中那条规则。

它一直没被抓住，是因为判据是**手设**计数器的：

```rust
set_counter(&mut state, &actor, "champ_exec", 1);   // 程序自己从来没写过这个 1
```

这正是"判据把程序该做的事替它做了"的形状 —— 与 §326 之前 `Doubt` 那条判据同一个病。

修法（不改内核，只用既有的"相对计数器"）：

* `anger`：`champ_exec = -1`（"欠一次 Execute"）；
* `execute`：`champ_exec = 0`（绝对）；
* 四个随机招（heavy_slash / face_slap / defensive_stance / gloat）：`champ_exec += 1`（相对）；
* 规则拆成两条：`champ_exec < 0` ⇒ Execute（Anger 之后那一次），
  `champ_exec >= 2` ⇒ Execute（此后每两招一次）。

Taunt 不计入（它不是 wiki 说的那两招"Random Move"）。
"""

import io
import json

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'

doc = json.load(io.open(CONTENT, encoding='utf-8'))
actions = {a['Id']: a for a in doc['EnemyActions']}


def counter_node(key, value, relative=False):
    return {
        'kind': 'node.setCombatantCounter',
        'value': {
            'TargetSelector': {
                'kind': 'sel.source',
                'value': {'Cardinality': 'ZeroOrOne', 'RequiredContextCapabilities': 'Source'},
            },
            'CounterId': {'value': key},
            'Amount': {'kind': 'const', 'value': {'Value': value}},
            'Relative': relative,
            'ResultKey': None,
        },
    }


def bump(action_id, key, value, relative=False):
    program = actions[action_id]['Program']
    assert program['Root']['kind'] == 'node.sequence', action_id
    children = program['Root']['value']['Children']
    assert not any(
        c.get('kind') == 'node.setCombatantCounter'
        and c['value']['CounterId']['value'] == key for c in children), action_id
    children.append(counter_node(key, value, relative))
    print('%-30s %s %s%d' % (action_id, key, '+=' if relative else '=', value))


# ── 1. anger：欠一次 Execute ───────────────────────────────────────────────────
anger = actions['the_champ.anger']['Program']['Root']['value']['Children']
exec_counter = [c for c in anger
                if c.get('kind') == 'node.setCombatantCounter'
                and c['value']['CounterId']['value'] == 'champ_exec']
assert len(exec_counter) == 1
assert exec_counter[0]['value']['Amount']['value']['Value'] == 0
exec_counter[0]['value']['Amount']['value']['Value'] = -1
print('the_champ.anger                champ_exec = -1 (an Execute is owed)')

# ── 2. execute：用掉它，并从 0 开始数 ─────────────────────────────────────────
bump('the_champ.execute', 'champ_exec', 0)

# ── 3. 四个随机招各自 +1 ──────────────────────────────────────────────────────
for action_id in ('the_champ.heavy_slash', 'the_champ.face_slap',
                  'the_champ.defensive_stance', 'the_champ.gloat'):
    bump(action_id, 'champ_exec', 1, relative=True)

# ── 4. 规则：拆成"欠一次"与"攒够两次" ─────────────────────────────────────────
encounter = [e for e in doc['Encounters'] if e['Id']['Value'] == 'enc_the_champ'][0]
champ = encounter['Enemies'][0]
rules = champ['IntentRules']
execute_rule = [r for r in rules
                if r.get('Action', {}).get('value') == 'the_champ.execute']
assert len(execute_rule) == 1
old = execute_rule[0]
assert old['Priority'] == 85
assert old['Condition']['value']['Conditions'][1]['value']['Op'] == 'LessOrEqual'
owed = json.loads(json.dumps(old))
owed['Condition']['value']['Conditions'][1]['value'] = {
    'Counter': {'value': 'champ_exec'}, 'Op': 'Less', 'Value': 0,
}
owed['Priority'] = 86
old['Condition']['value']['Conditions'][1]['value'] = {
    'Counter': {'value': 'champ_exec'}, 'Op': 'GreaterOrEqual', 'Value': 2,
}
rules.insert(rules.index(execute_rule[0]), owed)
print('the_champ rules               + champ_exec < 0 => Execute (priority 86)')
print('                              champ_exec >= 2 => Execute (priority 85)')

# Monsters 段是同一份的副本（§329 的教训：两份都要改）。
monsters = [m for m in doc['Monsters'] if m['Id'] == 'the_champ']
assert len(monsters) == 1
monsters[0]['IntentRules'] = champ['IntentRules']

io.open(CONTENT, 'w', encoding='utf-8', newline='\n').write(
    json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
print('content written')
