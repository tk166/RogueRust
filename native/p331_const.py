"""§331 收尾：把 `MAX_EVENT_RELIC_OFFER` 收到**一处**（`rd-core::content`），两边都引用它。

上一版把它定义在 `rd-run::state`，而 `content.rs` 里读 `RelicOffer` 的那一格又写了
`crate::content::MAX_EVENT_RELIC_OFFER` —— 一个数两个家，编译器当场就不认。
"""

import io

CORE = 'kernel/rd-core/src/content.rs'
STATE = 'kernel/rd-run/src/state.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


# ① rd-core：常量定义 + 文档
t = io.open(CORE, encoding='utf-8').read()
t = sub(t, "pub struct EventStep<'a> {",
        """/// §331：一个事件最多掷几件**遗物候选**（`N'loth` 的两件）。
///
/// 定义在 `rd-core`：读 `RelicOffer` 的那一格在 `content.rs` 里，而 `rd-run` 存候选的数组
/// 也要用同一个数 —— **一个数一处定义**，`rd-run` 直接 `pub use` 它。
pub const MAX_EVENT_RELIC_OFFER: usize = 2;

pub struct EventStep<'a> {""",
        'core const')
io.open(CORE, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-core: MAX_EVENT_RELIC_OFFER')

# ② rd-run：改成 re-export
t = io.open(STATE, encoding='utf-8').read()
OLD = '''/// §331：一个事件最多掷几件**遗物候选**（`N'loth` 的两件）。
///
/// 与 `MAX_EVENT_OPTIONS` 分开：那是"一段有几个按钮"，这是"按钮里能引用几件候选"。
/// 取 2 是因为 wiki 只给了 A/B 两件；再大不是"更强的内容"，而是把事件屏当列表用。
pub const MAX_EVENT_RELIC_OFFER: usize = 2;'''
NEW = '''/// §331：一个事件最多掷几件**遗物候选** —— 定义在 `rd-core::content`（读 `RelicOffer`
/// 的那一格与这里存候选的数组必须用**同一个数**），这里只是把它转出来给 `hash.rs` 用。
pub use rd_core::content::MAX_EVENT_RELIC_OFFER;'''
t = sub(t, OLD, NEW, 'state re-export')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)
print('rd-run: re-export')

# ③ hash.rs：用 rd-run 的那个名字
t = io.open(HASH, encoding='utf-8').read()
if 'rd_core::run_state_max_event_relic_offer' in t:
    t = t.replace('rd_core::run_state_max_event_relic_offer()',
                  'crate::state::MAX_EVENT_RELIC_OFFER')
    io.open(HASH, 'w', encoding='utf-8', newline='\n').write(t)
    print('hash.rs: constant name fixed')
else:
    print('hash.rs: already fine')
