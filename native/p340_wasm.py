"""§340 wasm 侧：`buy_potion` 多一个池子；§341 新增 `rd_run_in_fight()`（G16）。

## 为什么 `rd_run_buy_potion` 要池子

`buy_potion` 现在要补货（§340），补货需要**药水池**，与 `buy_relic` 要遗物池同一个理由。
ABI 的签名**不变**（`rd_run_buy_potion(slot)`）—— 池子由这一层从内容镜像里取，调用方不该
知道池子长什么样。

## 为什么加 `rd_run_in_fight`

八轮 Review 3.1：UI 场景表里 SC-03（战斗**待开始**）与 SC-03b（战斗中）无法用内核事实区分，
于是"未开始"只能是**页面自己记的** `mode`。而 `pending` 在两种情况下都是 `0`、
`node_resolved()` 战斗中仍是 false、`rd_env_done()` 在**没有会话**时返回 `1`（不可用）。
⇒ 场景表没法变成纯函数，3D 重写就得重新发明这条判断。

`rd_run_in_fight()`：`0` 不在战斗中 / `1` 在 / `-1` 没有局。它读的是 `RunSession.in_fight`，
那是 `fight_begin` 的**提交点**写的、`fight_end` 收尾时清的同一个字段 —— 与 `rd_run_archive_fill`
拒绝存档、`rd_run_replay_from` 拒绝回放用的是同一个判断，所以页面看到的就是内核看到的。
"""

import io

PATH = 'kernel/rd-wasm/src/run.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(PATH, encoding='utf-8').read()

# ── ① `rd_run_buy_potion`：从内容取药水池 ────────────────────────────────────
t = sub(t, '''    session.log(K_BUY_POTION, slot, -1, "");
    match session.state.buy_potion(slot as usize) {
        Ok(()) => 0,
        Err(e) => {
            let message = describe(&e);
            fail(session, &message)
        }
    }''',
        '''    session.log(K_BUY_POTION, slot, -1, "");
    // §340：`buy_potion` 现在要**药水池**（`the_courier` 的补货要用）。池子由这一层取，
    // ABI 的签名不变 —— 调用方不该知道池子长什么样，与 `rd_run_buy_relic` 同一个理由。
    let potions = potion_pool_of(content());
    match session.state.buy_potion(slot as usize, &potions) {
        Ok(()) => 0,
        Err(e) => {
            let message = describe(&e);
            fail(session, &message)
        }
    }''', 'buy_potion pool')

# ── ② 新导出 `rd_run_in_fight()`（§341 / 缺口 G16）───────────────────────────
ANCHOR = '''/// The seed of the current run, or `i32::MIN` if there is none.'''

NEW_EXPORT = '''/// §341：**这一局现在有没有一场正在打的战斗** —— `1` 有 / `0` 没有 / `-1` 没有局。
///
/// 为什么需要它（八轮 Review 3.1）：UI 的场景表里"战斗待开始"（SC-03）与"战斗中"（SC-03b）
/// 必须互斥，但内核此前**没有任何一格**能区分它们：
///
/// * `rd_run_pending()` 在两种情况下都是 `0`；
/// * `rd_run_node_resolved()` 在战斗中仍然是 false（要等 `fight_end` 才结算）；
/// * `rd_env_done()` 在**没有会话**时返回 `1`（"结束了"），所以它不能反过来说"有没有战斗"。
///
/// 于是"未开始"只能是**页面自己记的**一个标志（`web/index.html` 的 `mode`）—— 场景表没法变成
/// 纯函数，3D 重写就得重新发明这条判断。
///
/// 读的是 `RunSession.in_fight`：`rd_run_fight_begin` 的**提交点**写它、`rd_run_fight_end` 收尾
/// 时清它。同一格还被 `rd_run_archive_fill`（拒绝存档）与 `rd_run_replay_from`（拒绝回放）用来
/// 判断"战斗中"，所以页面看到的与内核看到的是同一个事实。
#[no_mangle]
pub extern "C" fn rd_run_in_fight() -> i32 {
    run_slot().as_ref().map_or(-1, |s| i32::from(s.in_fight))
}

/// The seed of the current run, or `i32::MIN` if there is none.'''

t = sub(t, ANCHOR, NEW_EXPORT, 'in_fight export')

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('run.rs: buy_potion pool + rd_run_in_fight')
