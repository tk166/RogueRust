"""§326 wasm：把 `mark_of_the_bloom` 的"不能治疗"带进**战斗**。

时点与 `set_combat_hero_health` 同一处：战斗**建好、第 1 回合还没开始**之前 —— 那正是
"这一场的事实"被写进去的位置（`ascension` 与英雄血量也在这一带）。晚于第 1 回合的话，
`burning_blood` 之类的回合初治疗就已经漏过去了。
"""

import io

LIB = 'kernel/rd-wasm/src/lib.rs'
RUN = 'kernel/rd-wasm/src/run.rs'


def sub(t, old, new, label, count=1):
    n = t.count(old)
    assert n == count, '%s: %d (want %d)' % (label, n, count)
    return t.replace(old, new)


t = io.open(LIB, encoding='utf-8').read()

t = sub(t, """pub(crate) fn set_combat_hero_health(value: i32) {""",
        """/// §326：`mark_of_the_bloom` —— 这一场战斗里治疗一律无效。
///
/// 单独一个函数而不是塞进 `set_combat_hero_health`：那个函数是"把血量搬进战斗"，
/// 这个是"把一条规则搬进战斗"，两件事写在两个地方才好各自被引用（判据也各问一次）。
pub(crate) fn set_combat_heal_blocked(blocked: bool) {
    if let Some(session) = slot().as_mut() {
        session.state.set_heal_blocked(blocked);
    }
}

pub(crate) fn set_combat_hero_health(value: i32) {""",
        'setter')

io.open(LIB, 'w', encoding='utf-8', newline='\n').write(t)
print('lib.rs: set_combat_heal_blocked')

t = io.open(RUN, encoding='utf-8').read()
t = sub(t, """                // The fight is built at the hero's maximum; a run usually enters wounded.
                crate::set_combat_hero_health(session.state.health());""",
        """                // The fight is built at the hero's maximum; a run usually enters wounded.
                crate::set_combat_hero_health(session.state.health());
                // §326：`mark_of_the_bloom` —— 战斗内的治疗也要挡（药水、卡牌、状态触发都走
                // `exec::heal_for`）。**第 1 回合之前**写，否则回合初的治疗已经漏过去了。
                crate::set_combat_heal_blocked(session.state.blocks_healing());""",
        'wire at fight begin')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)
print('run.rs: wired at fight begin')
