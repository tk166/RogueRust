"""修 §344 补丁把 `Pending` 的属性和我的枚举搅在一起的问题。

原状（补丁把 `pub enum Pending {` 换成了"新枚举 + 原签名"，于是 `Pending` 原有的
`#[derive(...)] #[repr(u8)]` 落到了 `RunEnd` 头上，`Pending` 变成了没有 `#[repr(u8)]`
的裸枚举）：

```
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]   <- 本来是 Pending 的
#[repr(u8)]                                             <- 本来是 Pending 的
/// §344：这一局结束了吗…
#[repr(u8)]                                             <- 我加的（冲突）
#[derive(...)]
pub enum RunEnd { ... }

pub enum Pending {                                       <- 丢了属性
```

修法：把 `Pending` 的文档 + 属性还给它，`RunEnd` 只留自己那一份。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

OLD = '''/// What the node under the cursor is waiting for.
///
/// A node is not settled by walking onto it (`env-abi.md` §11.5): walking sets the cursor, and
/// [`RunState::begin_node`] declares what the node then needs. Keeping the two apart is what lets
/// the map page walk a whole Act without pretending a fight happened.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
#[repr(u8)]
/// §344：这一局**结束了吗、为什么**。判别值就是 ABI 的值（`rd_run_over_why()`）。
///
/// 为什么需要它（缺口 G1）：页面前有一对**自己记的**模块级变量（`runOver` / `runOverWhy`）——
/// 战败时在 `endFight` 里置位、幕尽时在 `end_act` 里置位。于是"局终"不是**状态**的函数，
/// 而是**历史**的函数：存档回档之后、回放里、以及任何新写的渲染层都得重新发明它。
///
/// 四个值的判据在 [`RunState::run_end`]，顺序有意义：**死就是死**，哪怕地图也走完了。
#[repr(u8)]
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum RunEnd {
    /// 还能打。
    #[default]
    Ongoing = 0,
    /// 战败（`health <= 0`）。战斗收尾会把血量折回运行层，战败就是 0。
    Defeat = 1,
    /// **最后一幕**的 Boss 倒了。
    Victory = 2,
    /// 地图走完了（M1 的"这一幕到此为止"），由 [`RunState::end_act`] 记下。
    OutOfMap = 3,
}

pub enum Pending {'''

NEW = '''/// §344：这一局**结束了吗、为什么**。判别值就是 ABI 的值（`rd_run_over_why()`）。
///
/// 为什么需要它（缺口 G1）：页面前有一对**自己记的**模块级变量（`runOver` / `runOverWhy`）——
/// 战败时在 `endFight` 里置位、幕尽时在 `end_act` 里置位。于是"局终"不是**状态**的函数，
/// 而是**历史**的函数：存档回档之后、回放里、以及任何新写的渲染层都得重新发明它。
///
/// 四个值的判据在 [`RunState::run_end`]，顺序有意义：**死就是死**，哪怕地图也走完了。
#[repr(u8)]
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum RunEnd {
    /// 还能打。
    #[default]
    Ongoing = 0,
    /// 战败（`health <= 0`）。战斗收尾会把血量折回运行层，战败就是 0。
    Defeat = 1,
    /// **最后一幕**的 Boss 倒了。
    Victory = 2,
    /// 地图走完了（M1 的"这一幕到此为止"），由 [`RunState::end_act`] 记下。
    OutOfMap = 3,
}

/// What the node under the cursor is waiting for.
///
/// A node is not settled by walking onto it (`env-abi.md` §11.5): walking sets the cursor, and
/// [`RunState::begin_node`] declares what the node then needs. Keeping the two apart is what lets
/// the map page walk a whole Act without pretending a fight happened.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
#[repr(u8)]
pub enum Pending {'''

t = sub(t, OLD, NEW, 'repair attributes')
io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('attributes repaired')
