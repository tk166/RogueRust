"""§344 内核侧：G1（局终判据）+ G2（幕尽动作）+ G9（篝火回复量）。

## G1：这一局结束了吗、为什么 —— 内核给答案

页面前有一对**自己记的**模块级变量 `runOver` / `runOverWhy`：
`endFight` 里看到战败就置位，`end_act` 里本地置位。于是"局终"不是**状态**的函数，而是
**历史**的函数 —— 与 §341 的 `mode` 同一个病。存档回档、回放、3D 重写都得重新发明它。

新枚举 `RunEnd`（判别值就是 ABI 的值）：

| 值 | 名字 | 判据 |
|---:|---|---|
| 0 | `Ongoing` | 还能打 |
| 1 | `Defeat` | `health <= 0`（战斗收尾把血量折回来，战败就是 0） |
| 2 | `Victory` | `act >= MAX_ACT && boss_beaten`（最后一幕的 Boss 倒了） |
| 3 | `OutOfMap` | `end_act()` 被调用过（G2） |

顺序有意义：**死就是死**，哪怕地图也走完了。

## G2：幕尽是一个**动作**，不是一个页面状态

M1 的"第一幕到此为止"（地图最后一排、没有出边）以前只是页面把 `runOver` 置 true。
现在 `RunState::end_act()`：

* 只在**真的没事可做**时接受：`pending == None`、脚下的节点**已结算**、`reachable()` 为空；
* 否则响亮拒绝（`MapNotExhausted` / `NodeNotSettled` / `WrongPhase`），不改一个字节。

## G9：篝火回复量

`RunState::rest_heal()` 早就在，而且**算上了 `regal_pillow`（+15）与 `eternal_feather`
（每 5 张牌 +3）**。页面却自己算 `Math.floor(hpMax * 30 / 100)` —— 于是持那两件遗物时
**显示的数字是错的**（显示 +24，实际 +39）。这不是"分层不好看"，是**两个数**。
"""

import io

STATE = 'kernel/rd-run/src/state.rs'
STREAMS = 'kernel/rd-run/src/streams.rs'
ARCHIVE = 'kernel/rd-run/src/state/archive.rs'
HASH = 'kernel/rd-run/src/hash.rs'


def sub(text, old, new, label, count=1):
    n = text.count(old)
    assert n == count, '%s: 命中 %d 次（期望 %d）' % (label, n, count)
    return text.replace(old, new)


# ── ① 错误变体：地图还没走完 ────────────────────────────────────────────────
t = io.open(STREAMS, encoding='utf-8').read()
t = sub(t, '''    /// §343：这家店的删卡服务**这一趟已经用过了**。''',
        '''    /// §344：`end_act()` 被调用了，但地图**还有路可走**。
    ///
    /// 自己的变体而不是复用 `WrongPhase`：相位是对的（人就站在结算完的节点上），错的是
    /// "这一局还没到尽头"。页面要说的话（"还有路，往前走"）与"你不在那个房间"完全不同。
    MapNotExhausted,
    /// §343：这家店的删卡服务**这一趟已经用过了**。''', 'MapNotExhausted')
io.open(STREAMS, 'w', encoding='utf-8', newline='\n').write(t)

# ── ② RunEnd + 字段 + 两个方法 ──────────────────────────────────────────────
t = io.open(STATE, encoding='utf-8').read()

# 枚举放在 `Pending` 之前（同一个"运行层的小枚举"区）
t = sub(t, '''pub enum Pending {''',
        '''/// §344：这一局**结束了吗、为什么**。判别值就是 ABI 的值（`rd_run_over_why()`）。
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

pub enum Pending {''', 'RunEnd enum')

# 字段：紧挨 `boss_beaten`
t = sub(t, '''    boss_beaten: bool,''',
        '''    boss_beaten: bool,
    /// §344：`end_act()` 已经宣告"这一幕的地图走完了"（缺口 G2 的落点）。
    ///
    /// 为什么必须是**状态**而不是页面上的一个布尔：它一旦成立，这一局就结束了 —— 存档要存它、
    /// 指纹要算它（它决定下一步的合法动作集），而页面只是**读**它。
    pub(crate) ended_out_of_map: bool,''', 'field')

t = sub(t, '''            boss_beaten: false,''', '''            boss_beaten: false,
            ended_out_of_map: false,''', 'initializer')

# 访问器 + end_act（放在 `node_resolved` 之后，读者顺着"节点结算"读到"整局结束"）
t = sub(t, '''    pub fn node_resolved(&self) -> bool {''',
        '''    /// §344：这一局结束了吗、为什么（缺口 G1）。
    ///
    /// 顺序有意义：**死就是死** —— 血量归零时即使地图也走完了，答案仍是 `Defeat`。
    #[must_use]
    pub fn run_end(&self) -> RunEnd {
        if self.health <= 0 {
            return RunEnd::Defeat;
        }
        // 最后一幕的 Boss 倒了才算赢：前两幕的 `boss_beaten` 只表示"这一幕通关了"，
        // `mark_boss_beaten` 会换幕并把它清掉。
        if self.act >= MAX_ACT && self.boss_beaten {
            return RunEnd::Victory;
        }
        if self.ended_out_of_map {
            return RunEnd::OutOfMap;
        }
        RunEnd::Ongoing
    }

    /// §344（缺口 G2）：宣告"这一幕的地图走完了"。
    ///
    /// M1 的地图有 15 排，最后一排没有出边 —— 走到那儿就**没有下一步**了。以前这只是页面上的
    /// 一句话（`runOver = true`），现在它是一个**内核动作**：拒绝要响亮，接受要留痕。
    ///
    /// 三条前提，缺一不可（任何一条不成立都**不改一个字节**）：
    /// 1. 没有待决问句（`pending == None`）—— 有问句就还有事做；
    /// 2. 脚下的节点**已结算** —— 没结算就还有事做；
    /// 3. `reachable()` 为空 —— 还有路可走就还有事做。
    pub fn end_act(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::None {
            return Err(RunError::WrongPhase);
        }
        if self.node < 0 {
            return Err(RunError::WrongPhase);
        }
        if !self.node_resolved() {
            return Err(RunError::NodeNotSettled);
        }
        if !self.reachable().is_empty() {
            return Err(RunError::MapNotExhausted);
        }
        self.ended_out_of_map = true;
        Ok(())
    }

    pub fn node_resolved(&self) -> bool {''', 'run_end + end_act')
io.open(STATE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ③ 存档 ──────────────────────────────────────────────────────────────────
t = io.open(ARCHIVE, encoding='utf-8').read()
t = sub(t, '''const VERSION: u8 = 12;  // §343：`removed_this_shop`。''',
        '''const VERSION: u8 = 13;  // §344：`ended_out_of_map`。§343：`removed_this_shop`。''', 'version')
t = sub(t, '''    // §343：这家店的删卡服务用掉没有（`false`/`true` → 0/1）。
    writer.byte(u8::from(state.removed_this_shop))?;''',
        '''    // §343：这家店的删卡服务用掉没有（`false`/`true` → 0/1）。
    writer.byte(u8::from(state.removed_this_shop))?;
    // §344：这一幕的地图走完了没有（G2）。
    writer.byte(u8::from(state.ended_out_of_map))?;''', 'write')
t = sub(t, '''    // §343
    let removed_this_shop = reader.byte()?;''',
        '''    // §343
    let removed_this_shop = reader.byte()?;
    // §344
    let ended_out_of_map = reader.byte()?;''', 'read')
t = sub(t, '''    restored.removed_this_shop = removed_this_shop != 0;''',
        '''    restored.removed_this_shop = removed_this_shop != 0;
    restored.ended_out_of_map = ended_out_of_map != 0;''', 'restore')
t = sub(t, '''        // §343：这家店的删卡服务用掉了。**必须显式设**：留默认值 `false` 的话，
        // "漏还原一个字段就红"这句话对它就是假的（§308 的同一个教训）。
        run.removed_this_shop = true;''',
        '''        // §343：这家店的删卡服务用掉了。**必须显式设**：留默认值 `false` 的话，
        // "漏还原一个字段就红"这句话对它就是假的（§308 的同一个教训）。
        run.removed_this_shop = true;
        // §344：同上（G2 的"幕尽"）。
        run.ended_out_of_map = true;''', 'sample_full')
io.open(ARCHIVE, 'w', encoding='utf-8', newline='\n').write(t)

# ── ④ 指纹 ──────────────────────────────────────────────────────────────────
t = io.open(HASH, encoding='utf-8').read()
t = sub(t, '''        .str("removal_used=")
        .u32(u32::from(state.removed_this_shop))''',
        '''        .str("removal_used=")
        .u32(u32::from(state.removed_this_shop))
        // §344：幕尽（G2）。它一旦成立这一局就结束了，所以它决定下一步的合法动作集。
        .str("ended_out_of_map=")
        .u32(u32::from(state.ended_out_of_map))''', 'hash')
io.open(HASH, 'w', encoding='utf-8', newline='\n').write(t)
print('§344 kernel: RunEnd + end_act + archive v13 + hash')
