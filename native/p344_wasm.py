"""§344 的 ABI 侧：四个导出 + `BEAT_DESTROYED`（G11）。

| 导出 | 用途 | 缺口 |
|---|---|---|
| `rd_run_rest_heal()` | 篝火"休息"回多少（已含 `regal_pillow` / `eternal_feather`） | G9 |
| `rd_run_over()` | `1` 这一局结束了 / `0` 还能打 / `-1` 没有局 | G1 |
| `rd_run_over_why()` | `RunEnd` 的判别值：`0` 进行中 / `1` 战败 / `2` 通关 / `3` 地图走完了 | G1 |
| `rd_run_end_act()` | 宣告"这一幕的地图走完了"（`0` 接受 / `-2` 拒绝） | G2 |
| `BEAT_DESTROYED = 13` | `BeatKind::Destroyed` 的 ABI 名（`rd-core` 会发它，wasm 之前没有常量） | G11 |

G11 的判据要**穷尽**：`BeatKind::from_code(1..=13)` 全部有对应常量，`14` 没有 ——
这样"加了一个 beat kind 却忘了加 ABI 常量"（`FACT.md` §4.20 的同一个形状）会红。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
LIB = 'kernel/rd-wasm/src/lib.rs'
SMOKE = 'web/smoke.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 四个导出（挂在 `rd_run_in_fight` 旁边：同一族"运行层的权威事实"）────────
t = io.open(RUN, encoding='utf-8').read()
ANCHOR = '''/// The seed of the current run, or `i32::MIN` if there is none.'''

EXPORTS = '''/// §344（缺口 G9）：在篝火"休息"能回多少血；`-1` = 没有局。
///
/// **它必须来自内核**：`RunState::rest_heal()` 已经算上了 `regal_pillow`（+15）与
/// `eternal_feather`（每 5 张牌 +3），而页面此前自己写 `Math.floor(hpMax * 30 / 100)` ——
/// 持那两件遗物时**显示的数字是错的**（显示 +24、实际 +39）。那不是"分层不好看"，是**两个数**。
///
/// 为什么不是"返回一个百分比"：`eternal_feather` 那一项按**张数**算（每满 5 张 +3），
/// 与 `hpMax` 无关 —— 一个百分比表达不了它。
#[no_mangle]
pub extern "C" fn rd_run_rest_heal() -> i32 {
    run_slot().as_ref().map_or(-1, |s| s.state.rest_heal())
}

/// §344（缺口 G1）：这一局结束了吗 —— `1` 结束 / `0` 还能打 / `-1` 没有局。
///
/// 页面前有一对**自己记的**模块级变量（`runOver` / `runOverWhy`）：战败时在 `endFight` 里置位、
/// 幕尽时在 `end_act` 里置位。于是"局终"不是**状态**的函数，而是**历史**的函数 ——
/// 存档回档之后、回放里、以及任何新写的渲染层都得重新发明它（与 §341 的 `mode` 同一个病）。
#[no_mangle]
pub extern "C" fn rd_run_over() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |s| i32::from(s.state.run_end() != rd_run::state::RunEnd::Ongoing))
}

/// §344（缺口 G1）：为什么结束 —— `RunEnd` 的判别值：`0` 进行中 / `1` 战败 / `2` 通关 /
/// `3` 地图走完了（G2）；`-1` 没有局。
///
/// 与 `rd_run_over()` 分开是**故意的**：页面要显示的话完全不同（"第 N 层战败" vs "这一幕到此为止"），
/// 而一个 `1/0` 说不出这件事。数值是 `RunEnd` 的判别值，**不要重排**。
#[no_mangle]
pub extern "C" fn rd_run_over_why() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |s| i32::from(s.state.run_end() as u8))
}

/// §344（缺口 G2）：宣告"这一幕的地图走完了" —— `0` 接受 / `-2` 拒绝（原因在错误缓冲）/ `-1` 没有局。
///
/// 以前这只是页面上的一句话（`runOver = true`），于是"幕尽"不是内核事实：存档不存它、
/// 指纹不算它、回放看不见它。现在它有三条前提（没有待决问句 / 脚下节点已结算 /
/// `reachable()` 为空），任何一条不成立都**一个字节都不改**。
#[no_mangle]
pub extern "C" fn rd_run_end_act() -> i32 {
    let Some(session) = run_slot().as_mut() else {
        return -1;
    };
    session.log(K_END_ACT, -1, -1, "");
    let outcome = session.state.end_act().map(|()| 0i32);
    finish(session, outcome)
}

/// The seed of the current run, or `i32::MIN` if there is none.'''

t = sub(t, ANCHOR, EXPORTS, 'four exports')

# ── ② 新记录种类（脚本里要能回放这一动作）──────────────────────────────────
t = sub(t, '''const K_FIGHT_BEGIN: u8 = 20;''',
        '''const K_FIGHT_BEGIN: u8 = 20;
/// §344：`end_act`（幕尽）。它改变 `run_end()`，所以必须进脚本 —— 否则回放会在最后一步分叉。
const K_END_ACT: u8 = 21;''', 'K_END_ACT const')

t = sub(t, '''        K_FIGHT_BEGIN => "fight_begin",''',
        '''        K_FIGHT_BEGIN => "fight_begin",
        K_END_ACT => "end_act",''', 'kind name')

t = sub(t, '''        "fight_begin" => K_FIGHT_BEGIN,''',
        '''        "fight_begin" => K_FIGHT_BEGIN,
        "end_act" => K_END_ACT,''', 'kind from name')

t = sub(t, '''            K_BEGIN_EVENT => {
                let _ = rd_run_begin_event(payload.as_ptr(), payload.len() as i32);
            }''',
        '''            K_BEGIN_EVENT => {
                let _ = rd_run_begin_event(payload.as_ptr(), payload.len() as i32);
            }
            K_END_ACT => {
                let _ = rd_run_end_act();
            }''', 'replay dispatch')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ BEAT_DESTROYED ────────────────────────────────────────────────────────
t = io.open(LIB, encoding='utf-8').read()
t = sub(t, '''/// A combatant was created (split / summon). `a` = its ordinal, `b` = its maximum health.
pub const BEAT_SUMMONED: i32 = 12;''',
        '''/// A combatant was created (split / summon). `a` = its ordinal, `b` = its maximum health.
pub const BEAT_SUMMONED: i32 = 12;
/// §344（缺口 G11）：一个战斗员被**移出战斗**（`node.destroyCombatant`，§178）。
///
/// 与 [`BEAT_DOWNED`] 的区别：倒下的人**还在名册里**（触发器还能响），被移出的人**不在了**。
/// 这个常量以前**不存在** —— `rd-core::beat::BeatKind::Destroyed` 会发 13，而 ABI 只认到 12，
/// 于是任何消费者（页面、3D 渲染层、bench）都只能把 13 当成"未知种类"静默跳过。
pub const BEAT_DESTROYED: i32 = 13;''', 'BEAT_DESTROYED')
io.open(LIB, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ smoke.mjs 的手抄清单 ──────────────────────────────────────────────────
t = io.open(SMOKE, encoding='utf-8').read()
t = sub(t, '''  // §343: 这家店的删卡服务还能不能用（wiki: "once per Shop"）。''',
        '''  // §344: 缺口 G1/G2/G9 —— 局终判据、幕尽动作、篝火回复量。
  "rd_run_over", "rd_run_over_why", "rd_run_end_act", "rd_run_rest_heal",
  // §343: 这家店的删卡服务还能不能用（wiki: "once per Shop"）。''', 'smoke REQUIRED')
io.open(SMOKE, 'w', encoding='utf-8', newline='\n').write(t)
print('§344 wasm: four exports + K_END_ACT + BEAT_DESTROYED + smoke')
