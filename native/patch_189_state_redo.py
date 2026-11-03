"""§189: re-apply every `state.rs` change for A1/A10/A12/A20 in one pass.

Written after a spliced edit deleted 2 375 lines of this file: the rule is **one anchor, one exact
replacement, and verify with `cargo test` (which compiles the tests) -- not `cargo build`, which does
not**.
"""
import io
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PATH = os.path.join(ROOT, "kernel", "rd-run", "src", "state.rs")

EDITS = [
    # ---- constants -------------------------------------------------------------------------
    (
        """/// §188：事件变得更糟（wiki: *Unfavorable Events — many events have less positive outcomes
/// and more severe consequences*）。内容用 `Effects*Asc` 给出变体；没有变体的选项照旧。
pub const A_EVENTS_WORSE: u8 = 15;""",
        """/// §188：事件变得更糟（wiki: *Unfavorable Events — many events have less positive outcomes
/// and more severe consequences*）。内容用 `Effects*Asc` 给出变体；没有变体的选项照旧。
pub const A_EVENTS_WORSE: u8 = 15;
/// §189：精英更常见（wiki: *Elites are more common* — 8% → 16%）。
pub const A_ELITE_MORE: u8 = 1;
/// §189：开局带 Ascender's Bane（wiki: *Start with Ascender's Bane*）。
pub const A_START_CURSE: u8 = 10;
/// §189：升级牌更少（wiki: *Upgraded cards are less common*）—— 二三幕的升级概率减半。
pub const A_FEWER_UPGRADES: u8 = 12;
/// §189：第三幕两个 Boss（wiki: *Double Boss*）。
pub const A_DOUBLE_BOSS: u8 = 20;

/// A10 的诅咒。**不能被删** —— wiki 的卡面写着 "Cannot be removed"，而 StS 自己也是把这一条
/// 写在这张卡**自己**的代码里（它不是一个通用标签）。
pub const ASCENDERS_BANE: &str = "ascenders_bane";""",
    ),
    # ---- A20 field -------------------------------------------------------------------------
    (
        """    boss_beaten: bool,""",
        """    boss_beaten: bool,
    /// §189 `A20`: 这一幕已经倒下了几个 Boss（0 = 还没有，1 = 第一个已倒）。只有最后一幕 + A20
    /// 才会变成 1；换幕时归零。与 `boss_beaten` 同类：run 层状态，不进战斗指纹。
    bosses_fought: u8,""",
    ),
    (
        """            boss_beaten: false,""",
        """            boss_beaten: false,
            bosses_fought: 0,""",
    ),
    # ---- A1: the opening map knows the level; A10: the starting curse ----------------------
    (
        """        let map = RunMap::generate(&mut rng)?;""",
        """        let map = RunMap::generate_at(&mut rng, ascension)?;""",
    ),
    (
        """        for id in starting_deck {
            state.push_card(id)?;
        }
        state.check_invariants()?;""",
        """        for id in starting_deck {
            state.push_card(id)?;
        }
        // §189 `A10`：开局牌组里塞一张 Ascender's Bane（在牌组末尾，与其他"开局牌"一致）。
        if ascension >= A_START_CURSE {
            state.push_card(ASCENDERS_BANE)?;
        }
        state.check_invariants()?;""",
    ),
    # ---- A20: the second boss -------------------------------------------------------------
    (
        """        if self.act >= MAX_ACT {
            // The last act's boss: the run is won.
            self.boss_beaten = true;
            return;
        }""",
        """        if self.act >= MAX_ACT {
            // §189 `A20`：最后一幕要**两个** Boss。第一个倒下后节点重新可打（清 `resolved`），
            // 直到第二个也倒下才算赢。奖励屏照旧给两次：每一个 Boss 都是一场真的战斗。
            if self.at_least(A_DOUBLE_BOSS) && self.bosses_fought == 0 {
                self.bosses_fought = 1;
                // 调用方唯一的入口是"游标在 Boss 上、且节点没结算过" ⇒ 必须把节点重新打开。
                self.resolved = [0; 2];
                self.pending = Pending::None;
                return;
            }
            // The last act's boss: the run is won.
            self.boss_beaten = true;
            return;
        }""",
    ),
    (
        """        self.pending = Pending::None;
        self.resolved = [0; 2];
        self.boss_beaten = false;""",
        """        self.pending = Pending::None;
        self.resolved = [0; 2];
        self.boss_beaten = false;
        // §189：换幕重置"这一幕打了几个 Boss"。
        self.bosses_fought = 0;""",
    ),
    (
        """        match RunMap::generate(&mut rng) {""",
        """        match RunMap::generate_at(&mut rng, self.ascension()) {""",
    ),
    # ---- A10: the curse cannot be removed -------------------------------------------------
    (
        """        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        let price = self.remove_card_price();""",
        """        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        // §189 `A10`：Ascender's Bane 的卡面写着 "Cannot be removed"，StS 也把这一条写在这张卡
        // 自己的代码里。拒绝发生在**扣钱之前**，所以"拒绝 ⇒ 一个字节都不改"。
        if self.deck[card].as_str() == ASCENDERS_BANE {
            return Err(RunError::CannotRemove);
        }
        let price = self.remove_card_price();""",
    ),
    # ---- A12: the upgrade chance (base rule + halving) ------------------------------------
    (
        """pub fn reward_bands(kind: FightKind, offset: i32) -> (i32, i32) {""",
        """/// §189 `A12`：这张奖励牌有多大比例是**升级版**（百分比，整数）。
///
/// 基线（wiki `Card Rewards`）：第一幕 **0%**，第二幕 **12%**，第三幕 **25%**。
/// A12 是 "Upgraded cards are less common" ⇒ **减半**（6% / 12%）。
///
/// ⚠️ 基线这条规则以前**根本不存在** —— `inv:§3.5` 那句"第一幕不出现升级牌"被实现成了
/// "哪一幕都不出现"。所以 A12 是把两条一起做掉。
#[must_use]
pub const fn upgrade_chance_percent(act: u8, ascension: u8) -> i32 {
    let base = match act {
        1 => 0,
        2 => 12,
        3 => 25,
        _ => 0,
    };
    if ascension >= A_FEWER_UPGRADES {
        base / 2
    } else {
        base
    }
}

/// `id` 的 `+` 行，**如果池子里有**（§189）。
///
/// 不做字符串拼接再查表：id 是 `&'static str`，一次线性扫描比"拼一个 String 再比"更容易看出它
/// 到底在找什么（这个池子最多几十条）。
#[must_use]
fn upgraded_id<'a>(pool: &[PoolCard<'a>], base: &str) -> Option<&'a str> {
    pool.iter()
        .map(|card| card.id)
        .find(|id| id.len() == base.len() + 1 && id.starts_with(base) && id.ends_with('+'))
}

pub fn reward_bands(kind: FightKind, offset: i32) -> (i32, i32) {""",
    ),
    (
        """            used[index] = true;
            cards[slot] = RunId::new(card_pool[index].id).map_err(|_| RunError::BadId)?;""",
        """            used[index] = true;
            // §189 `A12`：先拿基础牌，再按概率换成它的 `+` 行。概率由**幕 + 难度**决定
            // （`upgrade_chance_percent`）；没有 `+` 行的牌保持原样、**不报错**（那是内容的事，
            // 内容门另有一条"每张可升级牌都必须有 `+` 行"的判据）。
            let mut chosen = card_pool[index].id;
            let chance = upgrade_chance_percent(self.act, self.ascension());
            if chance > 0 && self.rng.roll(RunStream::Reward, 100)? < chance as u32 {
                if let Some(upgraded) = upgraded_id(card_pool, chosen) {
                    chosen = upgraded;
                }
            }
            cards[slot] = RunId::new(chosen).map_err(|_| RunError::BadId)?;""",
    ),
    # ---- A12: `+` rows may never be picked as a *base* reward (both loops of `pick_of`) ----
    (
        """        let mut count = 0u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            let rarity = pool[*index].rarity;""",
        """        let mut count = 0u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            // §189 `A12`：`+` 行只能通过"升级抽取"进来。计数与定位是两次遍历，**两边都要跳过**，
            // 只跳一边会让第 i 张彩票落到不同的牌上（第一版就是这样，于是第一幕的奖励屏蹦出
            // 95 张升级牌 —— 比例比 100% 还高，因为位置全错）。
            if pool[*index].id.ends_with('+') {
                continue;
            }
            let rarity = pool[*index].rarity;""",
    ),
    (
        """        let mut target = self.rng.roll(RunStream::Reward, count)? as u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            let rarity = pool[*index].rarity;""",
        """        let mut target = self.rng.roll(RunStream::Reward, count)? as u32;
        for index in eligible {
            if used[*index] {
                continue;
            }
            if pool[*index].id.ends_with('+') {
                continue;
            }
            let rarity = pool[*index].rarity;""",
    ),
]


def main():
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in EDITS:
        if new in text:
            continue
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("state.rs: %d edits applied" % len(EDITS))


if __name__ == "__main__":
    main()
