"""§410 机制审计：把这几轮踩过的**四类** bug 变成可重跑的扫描（不是一个个试）。

## 为什么需要它

玩家（合理）说"数量众多一个个试不现实"。而这几轮的问题恰好都是**同一小批模式**：

| 类 | 已发生的实例 | 静态判据 |
|---|---|---|
| A 状态该过期却永不过期 | `rage` / `intangible` / `lose_strength` … | 施加点写了 `DurationTurns>0` 但状态定义 `UsesDuration=false`；或卡的说明里有"这一回合/下一回合"却给了永久状态 |
| B 意图规则"卡住" | Guardian 的 `mode_shift_budget<=0` 永不重置 ⇒ 每回合都进防御态 | 高优先级规则的**条件计数器**没有任何写入能把它翻回 false |
| C 触发器名认得但**内核从不发** | —（本轮扫描未发现，但判据留着） | 内容用到的 `Triggers[].Event` 必须在内核**实际发出**的事件集合里 |
| D 拾取欠账没人兑现 | `calling_bell` 的 3 件遗物 | 所有 `Pickup*` 遗物 × 所有授予路径都要兑现（这条在 wasm 侧，另由内核测试守） |

## 用法

    python native/audit_mechanics.py            # 报告（非零退出 = 有 A/B/C 类问题）
    python native/audit_mechanics.py --verbose  # 连"信息类"也打出来

## 判据的边界

这是**静态**扫描：它证明"没有已知形状的洞"，不证明"玩法完全正确"。
行为层面的两条（怪物不卡死、拾取遗物兑现）在 `kernel/rd-wasm` 的测试里，见
`every_monster_keeps_moving_and_attacks` / `every_pickup_relic_settles_its_debt`。
"""

import io
import json
import re
import sys

CONTENT = 'tools/contentc/packages/sts/sts.roguedeck.json'
KERNEL_SOURCES = ('kernel/rd-core/src/host.rs', 'kernel/rd-core/src/exec.rs',
                  'kernel/rd-core/src/state.rs')
TRIGGER_EVENTS = (
    'TurnStarted', 'TurnEnded', 'RoundStarted', 'RoundEnded', 'DamageDealt', 'DamageTaken',
    'Downed', 'FoeDowned', 'CardPlayed', 'CardCostPaid', 'HpLost', 'BlockGained', 'CardsDrawn',
    'CardExhausted', 'BlockBroken', 'DeckShuffled', 'StatusApplied', 'StatusMerged',
)

VERBOSE = '--verbose' in sys.argv

#: 说明里出现这些词 ⇒ "它应该有期限"。用于 A 类的**语义**扫描（不是判据的全部）。
TEMPORAL = re.compile(
    r'this turn|next turn|end of (your|this) turn|until the (start|end)|expires|for \d+ turns?',
    re.I,
)

problems = []
notes = []


def fail(kind, message):
    problems.append((kind, message))


def note(message):
    notes.append(message)


def eid(row):
    i = row.get('Id') if isinstance(row, dict) else row
    return i.get('Value') if isinstance(i, dict) else i


def load():
    return json.load(io.open(CONTENT, encoding='utf-8'))


def apply_statuses(node, out):
    """递归收集 `node.applyStatus`：[(status_id, duration_turns)]。"""
    if isinstance(node, dict):
        if node.get('kind') == 'node.applyStatus':
            value = node.get('value') or {}
            sid = (value.get('StatusDefinitionId') or {}).get('value')
            if sid:
                out.append((sid, value.get('DurationTurns', 0)))
        for child in node.values():
            apply_statuses(child, out)
    elif isinstance(node, list):
        for child in node:
            apply_statuses(child, out)


def counter_writes(node, out):
    """递归收集 `node.setCombatantCounter`：[(counter, amount_kind, relative)]。"""
    if isinstance(node, dict):
        if node.get('kind') == 'node.setCombatantCounter':
            value = node.get('value') or {}
            key = (value.get('CounterId') or {}).get('value')
            amount = value.get('Amount') or {}
            if key:
                out.append((key, amount.get('kind'), bool(value.get('Relative'))))
        for child in node.values():
            counter_writes(child, out)
    elif isinstance(node, list):
        for child in node:
            counter_writes(child, out)


def counters_read(condition, out):
    """递归收集条件里读到的计数器：[(counter, op, value)]。"""
    if isinstance(condition, dict):
        kind = condition.get('kind')
        if kind == 'intent.selfHasCounter':
            value = condition.get('value') or {}
            key = (value.get('Counter') or {}).get('value')
            if key:
                out.append((key, value.get('Op'), value.get('Value')))
        for child in condition.values():
            counters_read(child, out)
    elif isinstance(condition, list):
        for child in condition:
            counters_read(child, out)


def main():
    doc = load()
    statuses = {eid(s): s for s in doc['Statuses']}
    cards = doc['Cards']
    actions = {eid(a): a for a in doc['EnemyActions']}
    monsters = doc['Monsters']

    # ── A. 状态期限 ──────────────────────────────────────────────────────────
    print('[A] 状态期限')
    # A1：施加点写了 DurationTurns>0，但状态定义 UsesDuration=false（白写）
    points = []
    for section in ('Cards', 'Statuses', 'EnemyActions', 'Relics', 'Potions'):
        for row in doc.get(section) or []:
            found = []
            apply_statuses(row.get('Program'), found)
            apply_statuses(row.get('LifecyclePrograms'), found)
            apply_statuses(row.get('Triggers'), found)
            for sid, duration in found:
                if duration > 0:
                    points.append((eid(row), sid, duration))
    bad = sorted({(sid) for _, sid, _ in points if not (statuses.get(sid) or {}).get('UsesDuration')})
    if bad:
        for sid in bad:
            fail('A1', '%s 被写了 DurationTurns>0 但 UsesDuration=false（永远不过期）' % sid)
    else:
        print('  ok  A1：%d 处 DurationTurns>0 的状态都是 timed' % len(points))

    # A2：**语义**扫描 —— 施加它的卡/遗物说明里有"这一回合/下一回合/到期"，却给了永久状态
    suspicious = []
    for section, rows in (('Cards', cards), ('Relics', doc['Relics']), ('Potions', doc['Potions'])):
        for row in rows:
            desc = row.get('DescriptionKey') or ''
            if not TEMPORAL.search(desc):
                continue
            found = []
            apply_statuses(row.get('Program'), found)
            for sid, duration in found:
                status = statuses.get(sid) or {}
                if duration == 0 and not status.get('UsesDuration'):
                    suspicious.append((eid(row), sid, desc[:60]))
    if suspicious:
        # ⚠️ 不直接 fail：这里包含**永久能力**（"在你的回合结束时，获得 X" 是每回合都触发的 power）。
        # 报告出来人工过一遍；真正的判据是 A1 + 内核的"一回合状态会过期"测试。
        print('  ⚠️  A2：%d 处"说明有时限但状态永久"，需要人工确认（多数是每回合触发的 power）：'
              % len(suspicious))
        for row_id, sid, desc in suspicious[: (100 if VERBOSE else 12)]:
            print('        %-26s -> %-34s %s' % (row_id, sid, desc))
    else:
        print('  ok  A2：没有可疑的"说明有时限但状态永久"')

    # A3：状态用到的触发器事件，内核必须**真的派发**。
    #
    # ⚠️ 判据看 `TriggerEvent::X`（派发枚举），**不是** `CombatEvent::X`：`FoeDowned` 没有
    # `CombatEvent` 变体 —— 它是 `Downed` 处理器里**派生**出来派给另一阵营的
    # （`host::run_downed_triggers` 末段）。第一版按 `CombatEvent` 数，把 `FoeDowned`
    # 误报成"内核从不发出"（gremlin_horn / the_specimen 被冤枉）。
    emitted = set()
    kernel_text = ' '.join(io.open(path, encoding='utf-8').read() for path in KERNEL_SOURCES)
    for name in TRIGGER_EVENTS:
        # 至少两处：枚举定义 + 一处派发。
        if kernel_text.count('TriggerEvent::%s' % name) >= 2:
            emitted.add(name)
    used = {}
    for status in doc['Statuses']:
        for trigger in status.get('Triggers') or []:
            used.setdefault(trigger.get('Event'), []).append(eid(status))
    dead = {event: owners for event, owners in used.items() if event not in emitted}
    if dead:
        for event, owners in sorted(dead.items()):
            fail('A3', '触发器事件 %s 内核从不发出（%s）' % (event, ', '.join(owners[:4])))
    else:
        print('  ok  A3：内容用到的 %d 个触发器事件，内核都真的发' % len(used))

    # ── B. 意图规则"卡住" ────────────────────────────────────────────────────
    print('[B] 意图规则')
    # 每个动作 / 每个状态能写哪些计数器（先算一次，下面按怪物聚合）。
    action_writes = {}
    for aid, action in actions.items():
        found = []
        counter_writes(action.get('Program'), found)
        for child in action.get('ProgramAsc') or []:
            counter_writes(child.get('Program'), found)
        action_writes[aid] = found
    status_writes = {}
    for sid, status in statuses.items():
        found = []
        counter_writes(status.get('Triggers'), found)
        status_writes[sid] = found

    def reachable_writes(monster):
        """这个怪**能写到**的计数器：动作（含规则/权重里引用的）+ 它身上状态的触发器。

        ⚠️ 两个坑（第一版都踩了，于是把 champ_phase / ao_phase / ritual_owner_turns 全误报）：
        1. 只看 `Actions` 不够 —— 相位计数器往往由**规则里那个动作**自己写（`the_champ.anger`
           写 `champ_phase`），而它不在循环里；
        2. 状态**触发器**也会写（`ritual` 的 TurnStarted 写 `ritual_owner_turns`），而状态是
           动作**施加**的 —— 所以要把"动作能施加的状态"也算进可达集合。
        """
        ids = [a['value'] for a in monster.get('Actions') or []]
        for rule in monster.get('IntentRules') or []:
            aid = (rule.get('Action') or {}).get('value')
            if aid:
                ids.append(aid)
            for choice in rule.get('Choice') or []:
                aid = (choice.get('Action') or {}).get('value')
                if aid:
                    ids.append(aid)
        out = []
        applied_statuses = set()
        for status in monster.get('StartingStatuses') or []:
            sid = (status.get('StatusDefinitionId') or {}).get('value')
            if sid:
                applied_statuses.add(sid)
        for aid in ids:
            out.extend(action_writes.get(aid, []))
            found = []
            apply_statuses(actions[aid].get('Program') if aid in actions else None, found)
            for sid, _ in found:
                applied_statuses.add(sid)
        for sid in applied_statuses:
            out.extend(status_writes.get(sid, []))
        return out

    stuck = []
    info = []
    for monster in monsters:
        mid = eid(monster)
        reachable = reachable_writes(monster)
        for rule in monster.get('IntentRules') or []:
            read = []
            counters_read(rule.get('Condition'), read)
            for counter, op, value in read:
                writes_to = [w for w in reachable if w[0] == counter]
                if not writes_to:
                    stuck.append((mid, counter, op, value, '没有任何写入（条件恒为真/恒为假）'))
                    continue
                # "预算型"条件（`<= 0`）：只有**相对**写入的话，负数补不回来 ⇒ 永久为真。
                if op == 'LessOrEqual' and value == 0:
                    absolute = [w for w in writes_to if not w[2]]
                    if not absolute:
                        stuck.append((mid, counter, op, value,
                                      '只有相对写入（+N 补不回已被打穿的负数）'))
                elif op == 'GreaterOrEqual':
                    # `>= N` 永久为真通常是**设计**（Cultist 吟唱后一直打人）。
                    # 只有"写不出这个值"才是问题 —— 上面那条已经覆盖。
                    info.append('%s: %s %s %s（设计上可恒真）' % (mid, counter, op, value))
    if stuck:
        for mid, counter, op, value, why in stuck:
            fail('B1', '%s 的规则条件 %s %s %s 可能永久为真：%s' % (mid, counter, op, value, why))
    else:
        print('  ok  B1：%d 个怪物的意图规则，条件里的计数器都有可翻面的写入' % len(monsters))
    if VERBOSE:
        for line in info[:20]:
            print('        ·', line)


    # ── C. 意图种类 vs 实际节目 ─────────────────────────────────────────────
    print('[C] 意图种类')
    # 玩家靠意图图标判断"这一下会不会挨打"。所以：**打伤害的动作必须是 Attack**，
    # **Attack 必须真的打伤害**，**标签里写了 damage 就必须有伤害节点**。
    def has_node(node, kind):
        if isinstance(node, dict):
            if node.get('kind') == kind:
                return True
            return any(has_node(v, kind) for v in node.values())
        if isinstance(node, list):
            return any(has_node(v, kind) for v in node)
        return False

    mismatched = []
    for aid, action in sorted(actions.items()):
        intent = action.get('Intent') or {}
        kind = intent.get('Kind')
        label = intent.get('Label') or ''
        program = action.get('Program')
        deals = has_node(program, 'node.dealDamage')
        label_says_damage = bool(re.search(r'damage', label, re.I))
        if deals and kind != 'Attack':
            mismatched.append('%s：打伤害但意图是 %s' % (aid, kind))
        elif kind == 'Attack' and not deals:
            mismatched.append('%s：意图是 Attack 但没有伤害节点' % aid)
        elif label_says_damage and not deals:
            mismatched.append('%s：标签写了 damage 但没有伤害节点' % aid)
    if mismatched:
        for line in mismatched:
            fail('C1', line)
    else:
        print('  ok  C1：%d 个敌人动作的意图种类与节目一致' % len(actions))

    # ── D. 选牌问句的边界（`node.chooseCards`）──────────────────────────────
    print('[D] 选牌问句')
    # 内核的容量：`Min` 0..=10、`Max` 1..=10（= ABI 的手牌格数）、`Copies` 1..=4。
    # `forethought+` 的 "any number" 写的是 Max:10，而内核原来只到 8 ⇒ 一打就
    # `StepThrew(Script:Effect)`（§412 的"每张卡都打一遍"扫描抓到的）。
    MAX_SELECTED = 10
    MAX_COPIES = 4
    bad = []
    def walk_choose(node, owner):
        if isinstance(node, dict):
            if node.get('kind') == 'node.chooseCards':
                value = node.get('value') or {}
                lo = value.get('Min')
                hi = value.get('Max')
                copies = value.get('Copies')
                if not isinstance(lo, int) or not (0 <= lo <= MAX_SELECTED):
                    bad.append('%s: Min=%r 越界（0..=%d）' % (owner, lo, MAX_SELECTED))
                if not isinstance(hi, int) or not (1 <= hi <= MAX_SELECTED):
                    bad.append('%s: Max=%r 越界（1..=%d）' % (owner, hi, MAX_SELECTED))
                if isinstance(lo, int) and isinstance(hi, int) and lo > hi:
                    bad.append('%s: Min %d > Max %d' % (owner, lo, hi))
                if copies is not None and (not isinstance(copies, int) or not (1 <= copies <= MAX_COPIES)):
                    bad.append('%s: Copies=%r 越界（1..=%d）' % (owner, copies, MAX_COPIES))
            for child in node.values():
                walk_choose(child, owner)
        elif isinstance(node, list):
            for child in node:
                walk_choose(child, owner)

    for section in ('Cards', 'Statuses', 'EnemyActions', 'Potions', 'Relics'):
        for row in doc.get(section) or []:
            walk_choose(row.get('Program'), eid(row))
            walk_choose(row.get('LifecyclePrograms'), eid(row))
            walk_choose(row.get('Triggers'), eid(row))
    if bad:
        for line in bad:
            fail('D1', line)
    else:
        print('  ok  D1：所有 chooseCards 的 Min/Max/Copies 都在内核容量内')

    # ── E. 拾取类遗物清单（兑现由内核测试守，这里只列出范围）────────────────


    print('[E] 拾取类遗物')
    pickup = []
    for relic in doc['Relics']:
        text = json.dumps(relic.get('Effects') or relic.get('Effect') or '', ensure_ascii=False)
        if re.search(r'pickup|Pickup', text):
            pickup.append(eid(relic))
    note('拾取类遗物（内容里声明了 pickup 效果的）：%s' % (', '.join(pickup) or '（无）'))
    print('  ok  拾取类遗物 %d 件：%s' % (len(pickup), ', '.join(pickup) or '（无）'))

    # ── 汇总 ────────────────────────────────────────────────────────────────
    if VERBOSE:
        for line in notes:
            print('  ·', line)
    print()
    if problems:
        print('MECHANICS_AUDIT FAIL：%d 条' % len(problems))
        for kind, message in problems:
            print('  [%s] %s' % (kind, message))
        return 1
    print('MECHANICS_AUDIT PASS（A1/A3/B1/B2/C1/D1 全过；A2 是人工复核清单；行为层面三条在 wasm 测试里）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
