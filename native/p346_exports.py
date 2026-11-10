"""§346：四条小缺口（G3 / G6 / G7 / G12）。

| 缺口 | 导出 | 为什么值得加 |
|---|---|---|
| **G3** 页面靠遍历遗物找 `singing_bowl` | `rd_run_has_relic(ptr, len)` → `1/0/-1` | 页面有**两处**各写了一遍循环，而且"漏一件"不会红 |
| **G6** 没有事件/遭遇 id | `rd_run_event_id_len/into`、`rd_run_encounter_id_len/into` | 3D/美术要按 id 选背景，文本（一行描述）做不到 |
| **G7** 祝福数量写死 2 | `rd_run_start_offer_count()` | 内容一变就静默少画一个按钮 |
| **G12** "现在是谁的回合"只有诊断串 | `rd_env_active_slot()` → 墙位 | 文本里 `Exec(...)` 那种串不是给人读的 |

## 为什么 `has_relic` 值得一个导出

页面现在的写法是"遍历 `relicCount` 个遗物、逐个读 id、比字符串" —— 两个地方各一遍
（`singingBowl` 的奖励屏与加牌屏）。它不是错的，但它是**第二份知识**：
"哪件遗物决定哪个按钮"这件事在内核里有一份（`RELIC_SECOND_HALVES` / `holds_relic`），
在页面里又有一份（字符串相等）。两份里漏一处不会红 —— 只会有一个不出现的按钮。

## 为什么遭遇 id 放在**运行层**（`rd_run_*`）

`last_encounter` 是运行层的字段（§153：下一场战斗避免重复）。战斗期间它就是**这一场**的遭遇，
所以 `rd_run_encounter_id_*` 在战斗中给出的是当前遭遇 —— 而战斗结束后它仍然保留，
正好可以给"刚才打的是谁"用。放 `rd_env_*` 会假装它是战斗状态，其实不是。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
LIB = 'kernel/rd-wasm/src/lib.rs'
SMOKE = 'web/smoke.mjs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 运行层三条（has_relic / offer_count / event_id / encounter_id）────────
t = io.open(RUN, encoding='utf-8').read()

ANCHOR = '''/// §345：本幕 Boss 的**敌人 id**（`slime_boss` / `the_guardian` / …），`None` = 查不到。'''

EXPORTS = '''/// §346（缺口 G3）：身上有没有这件遗物 —— `1` 有 / `0` 没有 / `-1` 没有局。
///
/// 为什么值得一个导出：页面靠**遍历**遗物、逐个读 id、比字符串来回答这个问题，而且写了两遍
/// （奖励屏的 `singing_bowl` 与加牌屏的同一件）。那不是错，是**第二份知识**：
/// "哪件遗物决定哪个按钮"在内核里有一份（`holds_relic`），在页面里又有一份（字符串相等）。
/// 两份里漏一处不会红 —— 只会有一个不出现的按钮。
///
/// # Safety
///
/// `ptr` must point at `len` readable bytes (the id, as UTF-8).
#[no_mangle]
pub unsafe extern "C" fn rd_run_has_relic(ptr: *const u8, len: i32) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    if ptr.is_null() || len <= 0 {
        return 0;
    }
    let bytes = std::slice::from_raw_parts(ptr, len as usize);
    let Ok(id) = std::str::from_utf8(bytes) else {
        return 0;
    };
    i32::from(session.state.holds_relic(id))
}

/// §346（缺口 G7）：开局祝福**掷出了几个**。
///
/// 页面原来写死 `for slot in 0..2` —— 内容一变就静默少画一个按钮（而"少一个按钮"看起来
/// 就像"这一屏就这样"）。条数由内核给，页面按它循环。
#[no_mangle]
pub extern "C" fn rd_run_start_offer_count() -> i32 {
    run_slot()
        .as_ref()
        .map_or(0, |s| s.state.start_offers().map_or(0, |offers| offers.len() as i32))
}

/// §346（缺口 G6）：**光标下那个事件**的 id（`golden_idol` / …）；空串 = 现在没有事件。
///
/// 为什么给 id：3D/美术要按 id 选背景与立绘，而事件文本只是一行描述 —— 拿它当键会随文案改动
/// 而失效。名字由显示层决定（§345）。
#[no_mangle]
pub extern "C" fn rd_run_event_id_len() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    session.state.event().as_str().len() as i32
}

/// # Safety
///
/// `ptr` must point at `rd_run_event_id_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_event_id_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    write_out(session.state.event().as_str(), ptr)
}

/// §346（缺口 G6）：**这一场**（或刚打完的那一场）的遭遇 id（`enc_slime_boss` / …）。
///
/// 为什么在运行层而不是战斗层：`last_encounter` 是运行层的字段（§153：下一场避免重复）。
/// 战斗期间它就是这一场的遭遇；战斗结束后它仍然保留，正好给"刚才打的是谁"用。
/// 放 `rd_env_*` 会假装它是战斗状态，其实不是。
#[no_mangle]
pub extern "C" fn rd_run_encounter_id_len() -> i32 {
    run_slot()
        .as_ref()
        .map_or(-1, |s| s.state.last_encounter().as_str().len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_encounter_id_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_encounter_id_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    write_out(session.state.last_encounter().as_str(), ptr)
}

/// §345：本幕 Boss 的**敌人 id**（`slime_boss` / `the_guardian` / …），`None` = 查不到。'''

t = sub(t, ANCHOR, EXPORTS, 'run-layer exports')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② 战斗层：活跃战斗员的**墙位**（G12）───────────────────────────────────
t = io.open(LIB, encoding='utf-8').read()
ANCHOR2 = '''/// `rd_env_active_len()` 的实体'''

# 找不到那个注释就挂在 `rd_env_forced_turns` 前面（两者相邻）
if ANCHOR2 not in t:
    ANCHOR2 = '''/// How many times a turn has been cut short so far (`node.endTurn`), or `-1` with no session.'''

NEW = '''/// §346（缺口 G12）：**现在是谁的回合**，作为**墙位** —— `-1` 英雄 / `0..5` 敌人槽 /
/// `-2` 墙外或没人 / `-3` 没有会话。
///
/// 与 `rd_env_active_len()` 的区别：那个返回的是**诊断串**（`Exec(...)` 那种），
/// 给人看的；这个是给渲染层用的**数**（"高亮哪一格"）。两者都留着 —— 诊断串能说出
/// "卡在哪个节点"，而数说不出；墙位能直接索引，而串不能。
///
/// 墙位的编码与 observation / beat 完全一致（`env-abi.md` §10：槽位从不移动）。
#[no_mangle]
pub extern "C" fn rd_env_active_slot() -> i32 {
    let Ok(session) = ensure_session() else {
        return -3;
    };
    let Some(active) = session.state.active_combatant_id else {
        return -2;
    };
    // `wall_slot_of_ordinal` 要的是**序号**，而 `active_combatant_id` 是 id —— 扫一遍名册。
    for (ordinal, combatant) in session.state.combatants().iter().enumerate() {
        if combatant.id == active {
            return session.wall_slot_of_ordinal(ordinal as u8);
        }
    }
    -2
}

/// How many times a turn has been cut short so far (`node.endTurn`), or `-1` with no session.'''

t = sub(t, ANCHOR2, NEW, 'active_slot')
io.open(LIB, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ smoke.mjs ─────────────────────────────────────────────────────────────
t = io.open(SMOKE, encoding='utf-8').read()
t = sub(t, '''  // §345: 本幕 Boss 的**敌人 id**（显示层决定怎么念）。''',
        '''  // §346: 缺口 G3 / G6 / G7 / G12 —— 遗物查询、事件/遭遇 id、祝福数量、活跃墙位。
  "rd_run_has_relic", "rd_run_start_offer_count", "rd_run_event_id_len", "rd_run_event_id_into",
  "rd_run_encounter_id_len", "rd_run_encounter_id_into", "rd_env_active_slot",
  // §345: 本幕 Boss 的**敌人 id**（显示层决定怎么念）。''', 'smoke REQUIRED')
io.open(SMOKE, 'w', encoding='utf-8', newline='\n').write(t)
print('§346: has_relic / offer_count / event_id / encounter_id / active_slot')
