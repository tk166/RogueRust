"""§310（一）：`node.removeDebuffs` 的接线（ir 的 ALL 计数 + exec 的两处 match）。

这一轮只做"节点存在且能跑"，内容改动在下一个脚本里 —— 分开是为了让编译错误只来自
"枚举里多了一个变体"这一类必然的三处，而不是混在 JSON 改动里。
"""
import io

IR = 'D:/Vibe/sts-tui/kernel/rd-core/src/ir.rs'
EXEC = 'D:/Vibe/sts-tui/kernel/rd-core/src/exec.rs'


def patch(path, old, new, count=1):
    text = io.open(path, encoding='utf-8').read()
    assert text.count(old) == count, (path, text.count(old), old[:90])
    io.open(path, 'w', encoding='utf-8', newline='\n').write(text.replace(old, new))


def main():
    patch(IR, 'const ALL: [NodeKind; 42] = [', 'const ALL: [NodeKind; 43] = [')

    # preflight：`removeDebuffs` 与 `applyStatus` 同类 —— 立即生效、不走队列、不造成伤害，
    # 所以它就该落在"解析器可以直接走完"的这一组里。
    patch(EXEC, '''        | NodeKind::ApplyStatus
        | NodeKind::Heal''',
'''        | NodeKind::ApplyStatus
        // §310：清负面状态是直接写状态的节点（不进请求队列），所以预检时算"立即生效"。
        | NodeKind::RemoveDebuffs
        | NodeKind::Heal''')

    # 派发
    patch(EXEC, '        NodeKind::ApplyStatus => apply_status_node(node, ctx, frame, slot, stats),',
'''        NodeKind::ApplyStatus => apply_status_node(node, ctx, frame, slot, stats),
        NodeKind::RemoveDebuffs => remove_debuffs_node(node, ctx, frame, slot, stats),''')

    print('wiring done')


main()
