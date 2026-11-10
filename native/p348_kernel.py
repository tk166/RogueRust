"""§348 内核侧：P1-1（Boss 身份）+ P2-1（`rd_run_exists`）。

## P1-1：`rd_run_boss_id_*` 之前是**错的**

第十轮 Review 说得对：`boss_enemy_id(content, act)` 取的是**本幕 Boss 池的第一条**，而
`pick_encounter` 是在**开战时**从池里掷的（`RunStream::Combat`）。本内容每幕三个等权 Boss
（`enc_slime_boss / enc_the_guardian / enc_hexaghost` …），所以页面在三分之二的局里**预告了错的 Boss**。

修法：只回答**已经确定**的那一只 —— 即 `last_encounter` 落在**本幕 Boss 池**里时才是它；
否则返回空串（"还不知道"）。于是：

| 时点 | `last_encounter` | 查询结果 |
|---|---|---|
| Boss 战进行中 | 就是这一只 | **它** |
| 最后一幕 Boss 打完（SC-12a） | 就是它 | **它**（`mark_boss_beaten` 在最后一幕不换幕） |
| 站在 Boss 节点上、还没开打（SC-03） | 上一场（不是 Boss） | **空** —— 诚实地说"还不知道" |
| 刚换幕 | 上一幕的 Boss（不在本幕池里） | **空** |

⚠️ 这与 StS1 有一处**已知偏差**：原版在地图上就画着本幕的 Boss（进幕时就定了）。我们是开战时才掷。
⇒ 记为 `docs/sts-wiki-gap.md` 的待核偏差，不在这轮改运行层的随机流（那会动 RNG 消耗顺序，
而 `corpus` / `golden` 与存档都对它敏感）。

## P2-1：`rd_run_seed()` 的哨兵与合法 seed 冲突

`rd_run_seed()` 无局时返回 `i32::MIN`，而 `rd_run_start(i32::MIN, ..)` **没有拒绝**这个 seed ⇒
用那个 seed 开的局会让页面判成"未开局"（SC-00）。

⇒ 新增 `rd_run_exists()` → `1/0`。**"有没有局"和"seed 是多少"是两个问题**，不该共用一格。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


t = io.open(RUN, encoding='utf-8').read()

# ── ① `boss_enemy_id`：只回答"已经确定的那一只" ────────────────────────────
OLD = '''fn boss_enemy_id<'a>(content: &'a Content<'a>, act: u8) -> Option<&'a str> {
    let pool = match act {
        1 => "Boss",
        2 => "Boss2",
        3 => "Boss3",
        _ => return None,
    };
    let ids = content.encounter_pool(pool)?;
    let encounter_id = ids.iter().find(|id| !id.is_empty())?;
    let entry = content.lookup_in(encounter_id, rd_core::content::EK_ENCOUNTER)?;
    let enemies = content.encounter_enemies(u32::from(entry.index)).ok()?;
    let first = enemies.iter().next()?.ok()?;
    first.id().ok()
}'''

NEW = '''fn boss_enemy_id<'a>(content: &'a Content<'a>, act: u8, last_encounter: &str) -> Option<&'a str> {
    let pool = match act {
        1 => "Boss",
        2 => "Boss2",
        3 => "Boss3",
        _ => return None,
    };
    // §348：**只回答已经确定的那一只**。
    //
    // 之前这里取的是"本幕 Boss 池的第一条"，而 `pick_encounter` 是**开战时**才从池里掷的
    // （`RunStream::Combat`）。本内容每幕三个等权 Boss ⇒ 三分之二的局里页面**预告了错的 Boss**。
    //
    // 判据：`last_encounter`（`rd_run_fight_begin` 写的那个）落在**本幕 Boss 池**里 ⇒ 就是它。
    // 否则"还不知道"（站在 Boss 节点上还没开打、或刚换幕），返回空串 —— 不猜。
    let ids = content.encounter_pool(pool)?;
    if !ids.iter().any(|id| !id.is_empty() && *id == last_encounter) {
        return None;
    }
    let entry = content.lookup_in(last_encounter, rd_core::content::EK_ENCOUNTER)?;
    let enemies = content.encounter_enemies(u32::from(entry.index)).ok()?;
    let first = enemies.iter().next()?.ok()?;
    first.id().ok()
}'''
t = sub(t, OLD, NEW, 'boss_enemy_id')

# ── ② 两个调用点传 `last_encounter` ────────────────────────────────────────
t = sub(t, '''    boss_enemy_id(content(), session.state.act()).map_or(-1, |id| id.len() as i32)''',
        '''    boss_enemy_id(
        content(),
        session.state.act(),
        session.state.last_encounter().as_str(),
    )
    .map_or(-1, |id| id.len() as i32)''', 'len call site')

t = sub(t, '''    match boss_enemy_id(content(), session.state.act()) {
        Some(id) => write_out(id, ptr),
        None => 0,
    }''',
        '''    match boss_enemy_id(
        content(),
        session.state.act(),
        session.state.last_encounter().as_str(),
    ) {
        Some(id) => write_out(id, ptr),
        None => 0,
    }''', 'into call site')

# ── ③ 新导出 `rd_run_exists()`（P2-1）─────────────────────────────────────
ANCHOR = '''/// §346（缺口 G3）：身上有没有这件遗物 —— `1` 有 / `0` 没有 / `-1` 没有局。'''
EXPORT = '''/// §348（P2-1）：**现在有没有一局** —— `1` 有 / `0` 没有。
///
/// 为什么需要它：`rd_run_seed()` 用 `i32::MIN` 表示"没有局"，而 `rd_run_start(i32::MIN, ..)`
/// **没有拒绝**这个 seed ⇒ 用那个 seed 开的局会让页面判成"未开局"（SC-00）。
/// **"有没有局"和"seed 是多少"是两个问题**，不该共用一格。
///
/// 为什么不直接禁止 `i32::MIN` 当 seed：那会把一个哨兵变成一条**游戏规则**
/// （"这个种子不能用"），而玩家看不到理由。分成两个导出更便宜，也更诚实。
#[no_mangle]
pub extern "C" fn rd_run_exists() -> i32 {
    i32::from(run_slot().as_ref().is_some())
}

/// §346（缺口 G3）：身上有没有这件遗物 —— `1` 有 / `0` 没有 / `-1` 没有局。'''
t = sub(t, ANCHOR, EXPORT, 'run_exists export')
io.open(RUN, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ smoke 清单 ───────────────────────────────────────────────────────────
t = io.open('web/smoke.mjs', encoding='utf-8').read()
t = sub(t, '''  // §346: 缺口 G3 / G6 / G7 / G12 —— 遗物查询、事件/遭遇 id、祝福数量、活跃墙位。''',
        '''  // §348: "有没有局"（与 seed 分开）—— `i32::MIN` 是一个合法 seed。
  "rd_run_exists",
  // §346: 缺口 G3 / G6 / G7 / G12 —— 遗物查询、事件/遭遇 id、祝福数量、活跃墙位。''',
        'smoke REQUIRED')
io.open('web/smoke.mjs', 'w', encoding='utf-8', newline='\n').write(t)
print('§348 kernel: boss id = last_encounter in pool; rd_run_exists')
