"""§280：内容门认新原子（gold_cost / heal_pct / heal_full）+ 千分百分比 + RequiresAsc。"""
import io

P = 'D:/Vibe/sts-tui/native/sts_content_check.py'

OLD_PCT = '''                    if kind in ("damage_pct", "max_hp_pct"):
                        counts["percent"] += 1
                        # 百分比必须在 1..=100：`0` 是一条什么也不做的效果（页面上还写着
                        # "按上限 0% 受伤"），而 `150` 会把最大 HP 扣成负数。
                        try:
                            percent = int(payload)
                        except (TypeError, ValueError):
                            fail(where, "百分比不是整数: %r" % (payload,))
                            continue
                        if not 1 <= percent <= 100:
                            fail(where, "百分比 %d 不在 1..=100" % percent)
                        if entry.get("Amount") not in (0, None):
                            fail(where, "百分比效果的 Amount 必须是 0（数字在词里）")
                        continue'''

NEW_PCT = '''                    if kind in ("damage_pct", "max_hp_pct", "heal_pct"):
                        counts["percent"] += 1
                        # §280：百分比允许**一位小数**（真内容里有 12.5%）。解析规则与
                        # `rd-run::state::parse_permille` 逐条一致：1..=100、可选一位小数、
                        # 无符号。两边漂了会变成"内容门说 12.5 合法、内核当成非法"。
                        if not PERCENT_RE.match(payload or ""):
                            fail(where, "百分比 %r 不是 1..=100 的百分数（可带一位小数）"
                                 % (payload,))
                        elif float(payload) <= 0 or float(payload) > 100:
                            fail(where, "百分比 %r 不在 1..=100" % (payload,))
                        if kind == "heal_pct" and entry.get("Amount") not in (0, None):
                            fail(where, "百分比效果的 Amount 必须是 0（数字在词里）")
                        if kind != "heal_pct" and entry.get("Amount") not in (0, None):
                            fail(where, "百分比效果的 Amount 必须是 0（数字在词里）")
                        continue
                    if kind == "gold_cost":
                        counts["cost"] += 1
                        if not PAY_GOLD_RE.match(payload or ""):
                            fail(where, "gold_cost:%r 必须是正整数金币" % (payload,))
                        if entry.get("Amount") not in (0, None):
                            fail(where, "gold_cost 的 Amount 必须是 0（数字在词里）")
                    else:
                        pass'''

# 裸词表里补 heal_full
OLD_BARE = '''EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing",'''
NEW_BARE = '''EVENT_BARE_EFFECTS = ("heal", "gold", "damage", "max_hp", "nothing", "heal_full",'''

# 计数器
OLD_COUNTS = '''              "options": 0, "steps": 0, "conditional": 0, "conditions": 0}'''
NEW_COUNTS = '''              "options": 0, "steps": 0, "conditional": 0, "conditions": 0,
              "cost": 0}'''

# RequiresAsc 检查：插在 Requires 块之后
OLD_REQ_END = '''                if requires:
                    counts["conditional"] += 1'''
NEW_REQ_END = '''                if requires:
                    counts["conditional"] += 1
            # ── §280：A15 的条件变体（`RequiresAsc`）—— 与 `EffectsAsc` 成对出现。
            requires_asc = option.get('RequiresAsc')
            if requires_asc is not None:
                if not isinstance(requires_asc, list) or not requires_asc:
                    fail(label + '.RequiresAsc', "must be a non-empty list: %r" % (requires_asc,))
                elif requires is None:
                    fail(label + '.RequiresAsc',
                         "an A15 variant without a base `Requires` (the base is what A0-14 use)")
                else:
                    # ⚠️ 条件变体必须**真的不一样**：与 `EffectsAsc` 同一条规矩（§188）。
                    if requires_asc == requires:
                        fail(label + '.RequiresAsc',
                             "the A15 list equals the base -- this ascension changes nothing")
                    for index, atom in enumerate(requires_asc):
                        where = "%s.RequiresAsc%d" % (label, index)
                        check_requirement_atom(atom, where, relics, cards, counts)'''

OLD_ATOM_BLOCK_START = '''                for index, atom in enumerate(requires):
                    where = "%s.Requires%d" % (label, index)'''

def main():
    s = io.open(P, encoding='utf-8').read()

    # 词表常量
    old_kinds = '''REQUIRES_PRESENCE_OPS = ("has", "lacks")'''
    new_kinds = '''REQUIRES_PRESENCE_OPS = ("has", "lacks")

# §280：百分比现在**允许一位小数**（真内容里有 12.5%）。正则与
# `rd-run::state::parse_permille` 的规则逐条对应：1..=100、可选一位小数、无符号。
PERCENT_RE = re.compile(r"^(100|[0-9]{1,2})(\\.(?!0)[0-9])?$")
PAY_GOLD_RE = re.compile(r"^(?!0)[0-9]{1,3}$")'''
    assert s.count(old_kinds) == 1
    s = s.replace(old_kinds, new_kinds)

    assert s.count(OLD_BARE) == 1
    s = s.replace(OLD_BARE, NEW_BARE)
    if s.count(OLD_COUNTS) == 1:
        s = s.replace(OLD_COUNTS, NEW_COUNTS)
    assert s.count(OLD_PCT) == 1
    s = s.replace(OLD_PCT, NEW_PCT)
    assert s.count(OLD_REQ_END) == 1
    s = s.replace(OLD_REQ_END, NEW_REQ_END)

    # 把逐条原子检查抽成函数（两条 Requires 都调它）—— 一个词表只认一次
    start = s.index(OLD_ATOM_BLOCK_START)
    # 该块结束于 `                    counts["conditions"] += 1`
    end = s.index('                    counts["conditions"] += 1', start) + len(
        '                    counts["conditions"] += 1')
    block = s[start:end]
    # 反缩进 4 格，包成函数
    body_lines = []
    for line in block.split('\n'):
        body_lines.append(line[4:] if line.startswith('    ') else line)
    helper = ('def check_requirement_atom(atom, where, relics, cards, counts):\n'
              '    """一条 `Requires` 原子（§279/§280）。两条 `Requires*` 走同一个函数 —— \n'
              '    两份清单一定会漂，而漂了之后是"某一档的条件永远不成立".\n'
              '    """\n'
              + '\n'.join(body_lines) + '\n\n\n')
    s = s[:start] + '                for index, atom in enumerate(requires):\n' \
                     '                    check_requirement_atom(atom, "%s.Requires%d" % (label, index),\n' \
                     '                                           relics, cards, counts)' + s[end:]

    # 把 helper 插到 check_event_vocabulary 之前
    anchor = 'def check_event_vocabulary(doc):'
    assert s.count(anchor) == 1
    s = s.replace(anchor, helper + anchor)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('gate: §280 atoms + RequiresAsc (atom check factored out)')


main()
