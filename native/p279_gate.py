"""§279：内容门加 `Requires` 的判据（闭词表 + op 配套 + 反真空）。

四条，每条对应一种"没有症状"的错误：
1. **认不出的 kind / op** ⇒ 求值器报错，而 `rd_run_event_option_available` 的错路径会把按钮
   变成"永远不可选"（或永远可选）—— 两种都是屏幕正常、行为全错；
2. **op 与 kind 不配套**（`relic` 配 `at_least`）⇒ 同上；
3. **数值型缺 `Amount` / 存在型缺 `Id`** ⇒ 同上；
4. **整份内容里没有一条条件** ⇒ 这条机制没有任何人用，而它"存在"这件事只能靠测试记得；
   所以钉一条"至少有一条条件选项"，并且**同时要求它引用的 id 真的在内容里**。
"""
import io

P = 'D:/Vibe/sts-tui/native/sts_content_check.py'

ANCHOR = '''            # §188：A15 的变体必须**真的不一样**。'''

BLOCK = '''            # ── §279：条件（`Requires`）────────────────────────────────────────────
            requires = option.get('Requires')
            if requires is not None:
                if not isinstance(requires, list):
                    fail(label + '.Requires', "not a list: %r" % (requires,))
                    requires = []
                if not requires:
                    fail(label + '.Requires', "empty list -- a condition that asks nothing")
                if len(requires) > REQUIRES_MAX:
                    fail(label + '.Requires',
                         "%d atom(s) (the kernel's MAX_REQUIREMENTS is %d)"
                         % (len(requires), REQUIRES_MAX))
                for index, atom in enumerate(requires):
                    where = "%s.Requires%d" % (label, index)
                    kind_name = atom.get('Kind')
                    if kind_name not in REQUIRES_KINDS:
                        fail(where, "词表外的条件 %r" % (kind_name,))
                        continue
                    numeric = kind_name in REQUIRES_NUMERIC
                    allowed = REQUIRES_NUMERIC_OPS if numeric else REQUIRES_PRESENCE_OPS
                    op = atom.get('Op')
                    if op is None:
                        fail(where, "missing Op")
                        continue
                    if op not in allowed:
                        fail(where, "Op %r does not fit Kind %r (allowed: %s)"
                             % (op, kind_name, " / ".join(allowed)))
                        continue
                    if numeric:
                        amount = atom.get('Amount')
                        if not isinstance(amount, int):
                            fail(where, "numeric Kind needs an integer Amount, got %r" % (amount,))
                            continue
                        if kind_name == 'health_percent' and not 1 <= amount <= 100:
                            fail(where, "percentage %d is outside 1..=100" % amount)
                        if kind_name == 'ascension' and not 0 <= amount <= 20:
                            fail(where, "ascension %d is outside 0..=20" % amount)
                    else:
                        target = atom.get('Id')
                        if not isinstance(target, str) or not target:
                            fail(where, "presence Kind needs an Id, got %r" % (target,))
                            continue
                        if kind_name == 'relic' and target not in relics:
                            fail(where, "relic %r is not in Relics" % (target,))
                        if kind_name == 'card' and target not in cards:
                            fail(where, "card %r is not in Cards" % (target,))
                    counts["conditions"] += 1
                    counts["conditional_options" if index == 0 else "same"] += 0
                if requires:
                    counts["conditional"] += 1

'''
COUNT_KEYS = '''    counts = {"bare": 0, "curse": 0, "relic": 0, "percent": 0, "effects": 0, "asc": 0,
              "options": 0, "steps": 0, "conditional": 0, "conditions": 0}'''

OLD_COUNT_KEYS = '''    counts = {"bare": 0, "curse": 0, "relic": 0, "percent": 0, "effects": 0, "asc": 0,
              "options": 0, "steps": 0}'''

OLD_KINDS = '''# §278: `damage_pct:<n>` / `max_hp_pct:<n>` 的 kind（数字在词里，不在 Amount 格）。'''

KINDS = '''# §279：事件选项的条件（`Requires`）。词表与 `rd-core::run_expr` 的那两张表**必须一致** ——
# 不一致时判据在这里红，而如果只在求值器里漂，"点下去与画出来"就会判成两个不同的答案。
REQUIRES_MAX = 4
REQUIRES_KINDS = ("gold", "health", "max_health", "health_percent", "deck_count", "ascension",
                  "relic", "card")
REQUIRES_NUMERIC = ("gold", "health", "max_health", "health_percent", "deck_count", "ascension")
REQUIRES_NUMERIC_OPS = ("at_least", "at_most")
REQUIRES_PRESENCE_OPS = ("has", "lacks")

# §278: `damage_pct:<n>` / `max_hp_pct:<n>` 的 kind（数字在词里，不在 Amount 格）。'''


def main():
    s = io.open(P, encoding='utf-8').read()

    # ① 词表常量
    assert s.count(OLD_KINDS) == 1
    s = s.replace(OLD_KINDS, KINDS)
    # ② 计数桶
    if s.count(OLD_COUNT_KEYS) == 1:
        s = s.replace(OLD_COUNT_KEYS, COUNT_KEYS)
    else:
        assert s.count(COUNT_KEYS) == 1, 'counts line not found'
    # ③ 每条选项之后检查 Requires
    assert s.count(ANCHOR) == 1
    s = s.replace(ANCHOR, BLOCK + ANCHOR)
    # ④ 汇总行 + 反真空
    old_ok = '''    ok("event steps",
       "%d room(s) -> %d step(s) (%.2f steps/room), %d option(s), %d effect(s) "
       "(%d in A15 lists), %d bare / %d curse: / %d relic: / %d percent"
       % (len(rooms), counts["steps"], counts["steps"] / max(len(rooms), 1),
          counts["options"], counts["effects"], counts["asc"], counts["bare"],
          counts["curse"], counts["relic"], counts["percent"]))'''
    new_ok = '''    ok("event steps",
       "%d room(s) -> %d step(s) (%.2f steps/room), %d option(s), %d effect(s) "
       "(%d in A15 lists), %d bare / %d curse: / %d relic: / %d percent; "
       "%d conditional option(s) over %d atom(s)"
       % (len(rooms), counts["steps"], counts["steps"] / max(len(rooms), 1),
          counts["options"], counts["effects"], counts["asc"], counts["bare"],
          counts["curse"], counts["relic"], counts["percent"],
          counts["conditional"], counts["conditions"]))
    # ★ §279 反真空：条件机制没人用 == 它不存在。一条都没有时，`rd-core::run_expr` 的八条
    # 判据仍然全绿（它们喂的是人造事实）—— 而**镜像里没有一条 `Requires`**这件事，
    # 只有这一句能红。
    if counts["conditional"] == 0:
        fail("EventNodes", "no option has `Requires` -- the §279 condition layer is unused")'''
    assert s.count(old_ok) == 1
    s = s.replace(old_ok, new_ok)

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('content gate: Requires')


main()
