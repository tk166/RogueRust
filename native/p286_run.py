"""§286 rd-run：`EventMove`（一次选择的全部形状）+ 权重掷骰 + 进入效果 + 战斗档位。

## 为什么收成一个结构体

一次事件的"选择"现在有**五**样东西：这一段的效果、去哪一段、掷骰分支表、目标段的**进入
效果**、以及"这段是战斗吗"。五个位置参数里有两个是同样的"效果切片"，读代码时无法分辨
谁是谁 —— 而写错一个的后果是"奖励悄悄不发"或"进错段"，都不是编译错误。

## 一次选择的顺序（`Err` 时一个字节都不改）

    掷骰（推进随机流）→ 验目标段 id → 应用这一段的效果 → 应用**目标段**的进入效果
    → 落到目标段（或：收尾 / 转成一场战斗）

掷骰在最前面：随机流的位置不能随"效果里有没有 deck 改动"变化（§285 的纪律）。
"""
import io

P = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(s, old, new, count=1):
    assert s.count(old) == count, (s.count(old), old[:80])
    return s.replace(old, new)


def main():
    s = io.open(P, encoding='utf-8').read()

    # ── ① EventRoll → EventMove
    s = patch(s, '''/// §285：一次**事件掷骰** —— 成功去 `on_success`，失败去 `on_fail`。
///
/// 传进 [`RunState::resolve_event_effects`]，由**运行层**掷（`RunStream::Event`）：
/// 事件的随机是一局的账，不该消耗战斗的 `(seed, step)`。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventRoll<'a> {
    /// 成功概率（1..=100）。
    pub chance: u8,
    /// 成功时去的段（与选项的 `Next` 同一个 id 空间）。
    pub on_success: &'a str,
    /// 失败时去的段。
    pub on_fail: &'a str,
}''',
'''/// §286：**一次事件选择**的完整形状。传进 [`RunState::resolve_event_effects`]。
///
/// 五样东西各有名字，因为有两个是同样的切片类型（`effects` 与 `entry`），位置参数会让
/// "谁是谁"变成读代码时的猜谜。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EventMove<'a> {
    /// 这一段**选项自己的**效果，按顺序应用（§188）。
    pub effects: &'a [(EventEffect, Option<&'a str>)],
    /// 不掷骰时要去的那一段（空 = 这个选项是终点）。
    pub next: Option<&'a str>,
    /// §286：**权重分支** —— `(权重, 目标段)`，权重和 = 100。空 = 不掷骰。
    ///
    /// 比 §285 的 `Chance`/`NextFail` 更宽：`Dead Adventurer` 的一次搜索是四选一。
    pub branches: &'a [(u8, &'a str)],
    /// §286：**目标段的进入效果** —— `(段 id, 效果列表)`。运行层只按最终落点查一次。
    /// 有了它，"赢了赌注"就在**到达**结果屏时兑现，不必再让玩家点一次 `[Leave]`。
    pub entry: &'a [(&'a str, &'a [(EventEffect, Option<&'a str>)])],
    /// §286：这个选项是**一场战斗**。`0` = 不是，`1` = 普通，`2` = 精英。
    ///
    /// 选了它事件就收尾：房间由那一场战斗结算（`event_fight` 记住档位，`fight_end` 才
    /// `mark_resolved`）。这样"节点只付一次"仍然成立 —— 反复按"开打"不会刷出第二场。
    pub fight: u8,
}

impl<'a> EventMove<'a> {
    /// 什么都不做的一次选择（绝大多数的测试与"只收尾"的选项）。
    #[must_use]
    pub const fn none() -> EventMove<'static> {
        EventMove {
            effects: &[],
            next: None,
            branches: &[],
            entry: &[],
            fight: 0,
        }
    }

    /// 只带一个后继段的一次选择。
    #[must_use]
    pub const fn to(next: &'a str) -> EventMove<'a> {
        EventMove {
            next: Some(next),
            ..EventMove::none()
        }
    }
}''')

    # ── ② 签名：EventMove
    s = patch(s, '''    pub fn resolve_event_effects(
        &mut self,
        effects: &[(EventEffect, Option<&str>)],
        next: Option<&str>,
        roll: Option<EventRoll<'_>>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {''',
'''    pub fn resolve_event_effects(
        &mut self,
        event_move: &EventMove<'_>,
        pool: &[PoolCard<'_>],
    ) -> Result<(), RunError> {
        let &EventMove {
            effects,
            next,
            branches,
            entry,
            fight,
        } = event_move;''')

    # ── ③ 掷骰：权重表
    s = patch(s, '''        // `next` 在动手之前就要验：一个坏 id 必须在**一个字节都没改**之前被拒。
        //
        // §285：带 `roll` 时，先去**掷一次**（同样是"写之前"）—— 掷骰本身会推进随机流，
        // 所以它必须在所有 `self` 写入之前，和 `roll_unknown_room` 同一条纪律。
        let target = match roll {
            Some(roll) => {
                let rolled = self
                    .rng
                    .roll(RunStream::Event, 100)
                    .map_err(|_| RunError::Capacity)?;
                Some(if rolled < u32::from(roll.chance) {
                    roll.on_success
                } else {
                    roll.on_fail
                })
            }
            None => next,
        };''',
'''        // `next` 在动手之前就要验：一个坏 id 必须在**一个字节都没改**之前被拒。
        //
        // §286：有分支表时，先去**掷一次**（同样是"写之前"）—— 掷骰本身会推进随机流，
        // 所以它必须在所有 `self` 写入之前，和 `roll_unknown_room` 同一条纪律。
        //
        // 权重是**累积**读的：`rolled < 25` ⇒ 第一档，`< 50` ⇒ 第二档…… 最后一档吸收
        // "权重和没到 100"的零头 —— 内容门要求和恰好 100，但内核不靠内容正确才不越界。
        let target = if branches.is_empty() {
            next
        } else {
            let rolled = self
                .rng
                .roll(RunStream::Event, 100)
                .map_err(|_| RunError::Capacity)?;
            let mut edge = 0u32;
            let mut picked = branches[branches.len() - 1].1;
            for (weight, target) in branches {
                edge += u32::from(*weight);
                if rolled < edge {
                    picked = *target;
                    break;
                }
            }
            Some(picked)
        };''')

    # ── ④ 应用顺序：选项效果 → 目标段的进入效果
    s = patch(s, '''            if let Err(error) = self.apply_event_effect(*effect, *named, pool) {
                *self = before;
                return Err(error);
            }
        }
        match follow {''',
'''            if let Err(error) = self.apply_event_effect(*effect, *named, pool) {
                *self = before;
                return Err(error);
            }
        }
        // §286：**目标段的进入效果**（`(段 id, 效果)`）。同一个事务里应用 —— 失败就整个
        // 回滚，所以"金币到账了但改牌被拒"不会留下半截。
        //
        // 进入效果**不许改牌**（内容门拦）：改牌会变成待答问题，而问题队列只有一个位置，
        // 那个位置已经被这一段的选项用掉了。
        if let Some(effects) = entry
            .iter()
            .find(|(step, _)| *step == next_id.as_str())
            .map(|(_, effects)| *effects)
        {
            for (effect, named) in effects {
                if effect.deck_change().is_some() {
                    *self = before;
                    return Err(RunError::TwoDeckChanges);
                }
                if let Err(error) = self.apply_event_effect(*effect, *named, pool) {
                    *self = before;
                    return Err(error);
                }
            }
        }
        // §286：这一段的选项是**一场战斗** ⇒ 事件收尾、房间**不**结算（战斗结算它）。
        if fight != 0 {
            if follow.is_some() {
                // 改牌待答 + 战斗同时发生是不可能的：问句之后事件就收尾了，而收尾的
                // 责任在战斗。内容门也不许这样写。
                *self = before;
                return Err(RunError::TwoDeckChanges);
            }
            self.event = RunId::EMPTY;
            self.event_step = RunId::EMPTY;
            self.event_next = RunId::EMPTY;
            self.event_fight = fight;
            self.pending = Pending::None;
            return Ok(());
        }
        match follow {''')

    io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
    print('rd-run: EventMove + branches + entry + fight')
    print('NEXT: event_fight 字段 + 访问器 + mark_resolved 清空')


main()
