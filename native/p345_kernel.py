"""§345 内核侧：`rd_run_boss_id_*`（唯一真缺的那一格）。

## 用户给的架构方向（重要，写进注释）

**UI 显示的名字可以和内核的名字不一样**（规避版权等用途，通过映射表实现），所以**接口给 id 是好事**。

⇒ 缺口 G4 / G5 / G8 的定性要改：

| 缺口 | 原来的定性 | 实际 |
|---|---|---|
| G4 药水没有显示名 | "缺导出" | 药水 **id** 早就有（`rd_run_potion_id_*`），缺的是**显示层的映射** |
| G8 商店货架没有标题 | "缺导出" | 四排 **id** 早就有（`rd_run_shop_*_id_*`），同上 |
| G5 Boss 名写死 | "缺导出" | **真缺**：内核连 Boss 的 id 都没给出来 |

所以这一节只加一个导出（Boss 的敌人 id），其余交给 `web/ui_render.js` 的
`displayName()`（映射表 + 美化 id）。这也是"内核给事实、显示层给名字"这条线的第一次落地。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(RUN, encoding='utf-8').read()

ANCHOR = '''/// §344（缺口 G9）：在篝火"休息"能回多少血；`-1` = 没有局。'''

HELPER = '''/// §345：本幕 Boss 的**敌人 id**（`slime_boss` / `the_guardian` / …），`None` = 查不到。
///
/// 为什么给 **id** 而不是显示名：**UI 显示的名字可以和内核的名字不一样**（规避版权等用途，
/// 通过映射表实现）。所以这一层只负责"是哪一只"，名字由显示层决定 —— 见
/// `web/ui_render.js` 的 `displayName()`。
///
/// 来路：本幕的 Boss 池（`EncounterTables.Boss` / `Boss2` / `Boss3`，§130 按幕分池）→ 第一条遭遇
/// → `ENCT.Enemies[0].Id`。Boss 遭遇都是单只敌人（`Slime Boss` / `The Guardian` / …），
/// 所以"第一条遭遇的第一个敌人"就是那个 Boss。
fn boss_enemy_id<'a>(content: &'a Content<'a>, act: u8) -> Option<&'a str> {
    let pool = match act {
        1 => "Boss",
        2 => "Boss2",
        3 => "Boss3",
        _ => return None,
    };
    let ids = content.encounter_pool(pool)?;
    let encounter_id = ids.iter().find(|id| !id.is_empty())?;
    let entry = content.lookup_in(encounter_id, rd_core::content::EK_ENCOUNTER)?;
    let enemies = content.encounter_enemies(entry.index).ok()?;
    let first = enemies.iter().next()?.ok()?;
    first.id().ok()
}

/// §345（缺口 G5）：本幕 Boss 的敌人 id，写进调用方缓冲；`-1` = 没有局 / 查不到。
#[no_mangle]
pub extern "C" fn rd_run_boss_id_len() -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return -1;
    };
    boss_enemy_id(content(), session.state.act()).map_or(-1, |id| id.len() as i32)
}

/// # Safety
///
/// `ptr` must point at `rd_run_boss_id_len()` writable bytes.
#[no_mangle]
pub unsafe extern "C" fn rd_run_boss_id_into(ptr: *mut u8) -> i32 {
    let Some(session) = run_slot().as_ref() else {
        return 0;
    };
    match boss_enemy_id(content(), session.state.act()) {
        Some(id) => write_out(id, ptr),
        None => 0,
    }
}

/// §344（缺口 G9）：在篝火"休息"能回多少血；`-1` = 没有局。'''

t = sub(t, ANCHOR, HELPER, 'boss id export')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)
print('§345: rd_run_boss_id_len/into')
