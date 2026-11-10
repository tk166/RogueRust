"""§349：P1-1（A20 双 Boss 的身份窗口）+ P1-2（四处陈旧注释/文档）。

## P1-1：A20 第三幕，两只 Boss 之间的那个窗口

`boss_enemy_id` 现在只看"`last_encounter` 是否落在本幕 Boss 池里"。A20 第三幕的第一只 Boss 倒下后：

```rust
if self.at_least(A_DOUBLE_BOSS) && self.bosses_fought == 0 {
    self.bosses_fought = 1;
    self.resolved = [0; 2];     // 节点重新开放
    return;                     // 不换幕、不清 last_encounter
}
```

⇒ **第二只还没掷**（要到下一次 `fight_begin` 才掷），而 `last_encounter` 仍是**第一只**，
于是 `rd_run_boss_id_*` 在"第二场开打前"报的是**上一只**。那是"上一只 Boss 的身份"与
"即将挑战的 Boss 的身份"被合并了。

修法：把时间语义拆开，三条判据（顺序有意义）：

| 时刻 | 判据 | 回答 |
|---|---|---|
| 正在打 | `in_fight` | 就是 `last_encounter`（它就是这一场） |
| 双 Boss 之间（第一只已倒、第二只没掷、还没通关） | `!in_fight && !boss_beaten && bosses_fought == 1` | **未知**（空串） |
| 其余（含最后一幕 Boss 已倒的通关屏） | 落在本幕池里 | `last_encounter` |

⚠️ "通关屏"（`boss_beaten`）必须排在"双 Boss 之间"**前面**：第二只倒下之后
`bosses_fought` 仍然是 1，但那时我们**知道**它是谁（就是刚打完的那只）。

## P1-2：四处陈旧文字

代码改了、注释没改，比没写注释更糟 —— 下一个人会照注释理解实现。四处：

1. `run.rs` 的 `boss_enemy_id` 文档仍写"本幕的 Boss 池 → **第一条遭遇**"；
2. `ui_panels.js` 的 SC-00 注释仍写 `noRun` 来自 seed 哨兵；
3. `ui-state-model.md` §1 的 SC-00 判据、§3.2、§5 三处仍写 `rd_run_seed() == i32::MIN`；
4. 同一份文档 §3.3 的 `bossName` 仍写"无导出 / 页面写死 Slime Boss"。
"""

import io

RUN = 'kernel/rd-wasm/src/run.rs'
PANELS = 'web/ui_panels.js'
DOC = 'docs/ui-state-model.md'


def sub(path, old, new, label, count=1):
    t = io.open(path, encoding='utf-8').read()
    n = t.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    io.open(path, 'w', encoding='utf-8', newline='\n').write(t.replace(old, new))


# ── ① boss_enemy_id：拆开三种时间语义 ──────────────────────────────────────
sub(RUN, '''/// 来路：本幕的 Boss 池（`EncounterTables.Boss` / `Boss2` / `Boss3`，§130 按幕分池）→ 第一条遭遇
/// → `ENCT.Enemies[0].Id`。Boss 遭遇都是单只敌人（`Slime Boss` / `The Guardian` / …），
/// 所以"第一条遭遇的第一个敌人"就是那个 Boss。
fn boss_enemy_id<'a>(content: &'a Content<'a>, act: u8, last_encounter: &str) -> Option<&'a str> {''',
    '''/// 来路：**`last_encounter`**（`rd_run_fight_begin` 写的那一格）→ 它必须落在**本幕** Boss 池里
/// → `ENCT.Enemies[0].Id`。Boss 遭遇都是单只敌人（`Slime Boss` / `The Guardian` / …），
/// 所以"这场遭遇的第一个敌人"就是那个 Boss。
///
/// # 三种时间语义（§349，第十一轮 Review P1-1）
///
/// "上一只 Boss"与"即将挑战的 Boss"**不是同一个问题**，A20 第三幕会把它们分开：
///
/// | 时刻 | 回答 |
/// |---|---|
/// | 正在打（`in_fight`） | `last_encounter` —— 它就是这一场 |
/// | 双 Boss 之间（第一只已倒、第二只**还没掷**、还没通关） | **未知**（`None`） |
/// | 其余（含最后一幕 Boss 已倒的通关屏） | `last_encounter`（若在本幕池里） |
///
/// ⚠️ 第二只倒下之后 `bosses_fought` 仍然是 1，但那时我们**知道**它是谁（就是刚打完的那只）
/// —— 所以 `boss_beaten` 必须排在"双 Boss 之间"前面。
fn boss_enemy_id<'a>(
    content: &'a Content<'a>,
    act: u8,
    last_encounter: &str,
    in_fight: bool,
    bosses_fought: u8,
    boss_beaten: bool,
) -> Option<&'a str> {''', 'boss_enemy_id doc+signature')

sub(RUN, '''    // §348：**只回答已经确定的那一只**。''',
    '''    // §349：A20 第三幕的**第二只还没掷** —— 那时 `last_encounter` 仍是第一只，
    // 把它当成"即将挑战的那只"是错的（第十一轮 Review P1-1）。
    if !in_fight && !boss_beaten && bosses_fought == 1 {
        return None;
    }
    // §348：**只回答已经确定的那一只**。''', 'a20 guard')

# 两个调用点补参数
sub(RUN, '''    boss_enemy_id(
        content(),
        session.state.act(),
        session.state.last_encounter().as_str(),
    )
    .map_or(0, |id| id.len() as i32)''',
    '''    boss_enemy_id(
        content(),
        session.state.act(),
        session.state.last_encounter().as_str(),
        session.in_fight,
        session.state.bosses_fought(),
        session.state.boss_beaten(),
    )
    .map_or(0, |id| id.len() as i32)''', 'len call site')

sub(RUN, '''    match boss_enemy_id(
        content(),
        session.state.act(),
        session.state.last_encounter().as_str(),
    ) {''',
    '''    match boss_enemy_id(
        content(),
        session.state.act(),
        session.state.last_encounter().as_str(),
        session.in_fight,
        session.state.bosses_fought(),
        session.state.boss_beaten(),
    ) {''', 'into call site')

# ── ② ui_panels：SC-00 的注释 ─────────────────────────────────────────────
sub(PANELS, '''    // 1 未开局：没有局。`noRun` 来自 `rd_run_seed() == i32::MIN`。''',
    '''    // 1 未开局：没有局。`noRun` 来自 **`rd_run_exists()`**（§348）—— **不是** seed 哨兵：
    // `i32::MIN` 是一个合法 seed，拿它当"无值"会让那一局被判成未开局。''', 'SC-00 comment')
print('§349: A20 window + stale comment (run.rs / ui_panels.js)')
