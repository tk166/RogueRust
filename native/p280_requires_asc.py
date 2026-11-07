"""§280：条件也有 A15 变体（`RequiresAsc`）—— Cleric 的 Purify 是 50 → 75 金币。

为什么不能只写一条 `gold at_least 50`：A15 的价格是 75，于是"50..74 金币 + A15"会画出
一个点下去被拒的按钮（可见的死按钮）。也不能只写 75：低难度下 50..74 金币明明付得起。
条件与效果必须**同一对字段**（`Requires` / `RequiresAsc` 对 `Effects` / `EffectsAsc`）——
这也是"同一个词表被两处认识就一定漂"的反面：这里让两处**成对出现**。
"""
import io

P_CORE = 'D:/Vibe/sts-tui/kernel/rd-core/src/run_expr.rs'
P_CONTENT = 'D:/Vibe/sts-tui/kernel/rd-core/src/content.rs'
P_RUN = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:70])
    return s.replace(old, new)


def main():
    # ---------------------------------------------------------------- rd-core::run_expr
    s = io.open(P_CORE, encoding='utf-8').read()
    s = patch(s, '''/// 一条选项最多几个条件原子。''',
'''/// A15（"事件变糟"）的阈值 —— `rd-run::state::A_EVENTS_WORSE` 的同一个数。
///
/// 为什么在 `rd-core` 里再写一份：`rd-core` 不能依赖 `rd-run`（那是运行层）。漂移由
/// `rd-wasm` 的一条判据钉住（两条常量相等），这比让 `rd-core` 认识"事件"这个概念要好。
pub const A15: u8 = 15;

/// 一条选项最多几个条件原子。''')
    s = patch(s, '''    let mut terms = [0u16; MAX_REQUIREMENTS + 1];
    let count = node
        .term_list_field_or_empty("Requires", &mut terms)''',
'''    // §280：A15 的价目常常不同（`The Cleric` 的 Purify 50 → 75），于是**条件**也要有
    // `RequiresAsc`：它只在 A15 起生效，并且**取代**基础那一串（与 `EffectsAsc` 的语义相同）。
    let key = if facts.ascension >= A15
        && node.term_list_field_or_empty("RequiresAsc", &mut [0u16; MAX_REQUIREMENTS + 1])
            .map(|count| count > 0)
            .unwrap_or(false)
    {
        "RequiresAsc"
    } else {
        "Requires"
    };
    let mut terms = [0u16; MAX_REQUIREMENTS + 1];
    let count = node
        .term_list_field_or_empty(key, &mut terms)''')
    io.open(P_CORE, 'w', encoding='utf-8', newline='\n').write(s)

    # ---------------------------------------------------------------- rd-core::content
    c = io.open(P_CONTENT, encoding='utf-8').read()
    # 读选项时把 `RequiresAsc` 也带过来？不需要：求值器按 term 现读（与 §279 一致）。
    # 这里只把文档注释补上。
    c = patch(c, '''    /// §279：这个选项在镜像里的 term —— 条件（`Requires`）由''',
'''    /// §279/§280：这个选项在镜像里的 term —— 条件（`Requires` / `RequiresAsc`）由''')
    io.open(P_CONTENT, 'w', encoding='utf-8', newline='\n').write(c)

    # ---------------------------------------------------------------- rd-run：A15 常量对照
    r = io.open(P_RUN, encoding='utf-8').read()
    r = patch(r, '''pub const A_EVENTS_WORSE: u8 = 15;''',
'''pub const A_EVENTS_WORSE: u8 = 15;

// §280：`rd_core::run_expr::A15` 是同一个数的第二份（`rd-core` 不能依赖 `rd-run`）。
// `rd-wasm` 有一条判据钉住它们相等 —— 两个数字漂开会让"A15 的价目"与"A15 的条件"分家。''')
    io.open(P_RUN, 'w', encoding='utf-8', newline='\n').write(r)
    print('RequiresAsc + A15 const')


main()
