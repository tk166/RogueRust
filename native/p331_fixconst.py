"""§331 修：常量插到了 `#[derive]` 与 `struct` 之间（第一次插在 `pub struct EventStep` 之前，
而那一行上面是 derive）。把第一份删掉，只留 derive 后面那份，并补 `EMPTY` 的字段。
"""

import io

PATH = 'kernel/rd-core/src/content.rs'

# ① 删掉插错位置的第一份（它在 derive 与 struct 之间）。
BROKEN = """/// §331：一个事件最多掷几件**遗物候选**（ 的两件）。
///
/// 定义在  而不是 ：读  的那一格在  里，
/// 而  存候选的数组也用同一个数 —— **一个数一处定义**，两边都  它。
pub const MAX_EVENT_RELIC_OFFER: usize = 2;

"""

# ② 正确位置：`#[derive(...)]` 之后、`pub struct EventStep` 之前。
WRONG_ORDER = """#[derive(Clone, Copy, PartialEq, Eq, Debug)]
/// §331：一个事件最多掷几件**遗物候选**（`N'loth` 的两件）。
///
/// 定义在 `rd-core`：读 `RelicOffer` 的那一格在 `content.rs` 里，而 `rd-run` 存候选的数组
/// 也要用同一个数 —— **一个数一处定义**，`rd-run` 直接 `pub use` 它。
pub const MAX_EVENT_RELIC_OFFER: usize = 2;

pub struct EventStep<'a> {"""

RIGHT_ORDER = """#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct EventStep<'a> {"""

# 常量块放到 struct 定义**之后**的独立位置（`impl` 之前）。
CONST_BLOCK = """
/// §331：一个事件最多掷几件**遗物候选**（`N'loth` 的两件）。
///
/// 定义在 `rd-core`：读 `RelicOffer` 的那一格在 `content.rs` 里，而 `rd-run` 存候选的数组
/// 也要用同一个数 —— **一个数一处定义**，`rd-run` 直接 `pub use` 它。
pub const MAX_EVENT_RELIC_OFFER: usize = 2;
"""

t = io.open(PATH, encoding='utf-8').read()
assert t.count(BROKEN) == 1, 'broken block'
t = t.replace(BROKEN, '')
assert t.count(WRONG_ORDER) == 1, 'wrong order block'
t = t.replace(WRONG_ORDER, RIGHT_ORDER)

# ③ `EMPTY` 补字段。
OLD_EMPTY = """        entry_asc: [EffectSpec { effect: "nothing", amount: 0 }; MAX_EVENT_EFFECTS],
        entry_asc_count: 0,
        options: [EventOption {"""
NEW_EMPTY = """        entry_asc: [EffectSpec { effect: "nothing", amount: 0 }; MAX_EVENT_EFFECTS],
        entry_asc_count: 0,
        relic_offer: 0,
        options: [EventOption {"""
assert t.count(OLD_EMPTY) == 1, 'EMPTY anchor'
t = t.replace(OLD_EMPTY, NEW_EMPTY)

# ④ 常量块插到 `impl<'a> EventStep<'a> {` 之前。
IMPL = "impl<'a> EventStep<'a> {"
assert t.count(IMPL) == 1
t = t.replace(IMPL, CONST_BLOCK.strip() + "\n\n" + IMPL)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('content.rs fixed')
