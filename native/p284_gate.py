"""§284：内容门新增判据 —— **无目标事件**的触发器里不许用 `sel.eventTarget`。

## 为什么（这是 §283 真踩到的那个坑）

`TurnStarted` / `TurnEnded` / `FoeDowned` 这些事件**没有目标**：`sel.eventTarget` 在它们的触发器
程序里解析出**空集**，于是 `applyStatus` / `dealDamage` / `gainBlock` 一个目标都不碰 ——
**全静默**。§283 写 `snecko_eye` 时就这么写了：状态没挂上，而同一段里的 `drawCards`
（用 `sel.source`）成功了，症状是"抽了 7 张但没有 Confused"，查了很久。

参考语义本身是对的（没有目标就是空集，和"目标已经死了"是同一件事），所以**不能**在核心里
把它改成报错 —— `dealDamage(eventTarget)` 在目标已死时解析为空集是**正常**的。
但"在一个**永远不会**有目标的事件里用 `eventTarget`"是**内容的静态错误**，可以在这里拦。

判据形状：遍历每条状态/遗物的**触发器程序**，Event 属于无目标事件时，任何节点的
`TargetSelector`（以及条件里的选择器）都不许是 `sel.eventTarget`。
"""
import io

P = 'D:/Vibe/sts-tui/native/sts_content_check.py'

HELPER = '''# §284：**没有目标**的事件。它们的触发器程序里 `sel.eventTarget` 恒为空集 ⇒ 任何
# "对 eventTarget 做事"的节点都会静默什么都不做。参考语义是对的（空集不是错误），
# 所以这条只能在**内容**这一层拦（静态、响亮）。
INV_TARGETLESS_EVENTS = ("TurnStarted", "TurnEnded", "FoeDowned")


def check_targetless_trigger_selectors(doc):
    """§284：无目标事件的触发器里不许用 `sel.eventTarget`。"""
    print("[6g] targetless triggers (port-plan.md §284)")
    problems = 0
    checked = 0

    def visit(node, where):
        nonlocal problems
        if isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, "%s[%d]" % (where, index))
            return
        if not isinstance(node, dict):
            return
        kind = node.get("kind")
        if kind == "sel.eventTarget":
            fail(where, "`sel.eventTarget` in a trigger for an event that has no target -- "
                        "it resolves to the empty set, so the node silently does nothing")
            problems += 1
        for key, value in node.items():
            if key == "kind":
                continue
            visit(value, where + "." + key if where else key)

    def triggers_of(rows, label):
        nonlocal checked
        for row in rows or []:
            row_id = row.get("Id")
            for index, trigger in enumerate(row.get("Triggers") or []):
                event = trigger.get("Event")
                if event not in INV_TARGETLESS_EVENTS:
                    continue
                checked += 1
                visit(trigger.get("Program"),
                      "%s.%s.Triggers[%d](%s)" % (label, row_id, index, event))

    triggers_of(doc.get("Statuses"), "Statuses")
    triggers_of(doc.get("Relics"), "Relics")
    ok("targetless triggers", "%d trigger program(s) checked, %d bad selector(s)"
       % (checked, problems))


'''


def main():
    s = io.open(P, encoding='utf-8').read()
    anchor = 'def check_event_vocabulary(doc):'
    assert s.count(anchor) == 1
    s = s.replace(anchor, HELPER + anchor)
    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)

    # 调用点：找 `check_event_vocabulary(doc)` 的调用处（顺序无所谓，紧跟着就行）
    t = io.open(P, encoding='utf-8').read()
    call = '    check_event_vocabulary(doc)'
    if t.count(call) == 1:
        t = t.replace(call, call + '\n    check_targetless_trigger_selectors(doc)')
    else:
        raise SystemExit('call site not found: %d' % t.count(call))
    io.open(P, 'w', encoding='utf-8', newline='\n').write(t)
    print('gate: targetless trigger selectors')


main()
