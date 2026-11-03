"""§189 part 2: A10 (Ascender's Bane), A12 (fewer upgraded cards), A20 (double boss).

A12 needs a **base rule** that never existed: our reward roll offered no upgraded card at all (the
`inv:§3.5` note "act 1 never offers one" was implemented as "no act ever does"). So the rule is:

    act 1 -> 0%        act 2 -> 12%        act 3 -> 25%

and A12 halves each of those (6% / 12%), with the wiki's own reasoning: *"Upgraded cards are less
common"*. The percentages are integers because every other number in this run layer is.
"""
import io

PATH = "kernel/rd-run/src/state.rs"

# ---------------------------------------------------------------- A10: the starting curse

DECK_ANCHOR = """        for id in starting_deck {
            state.push_card(id)?;
        }
        state.check_invariants()?;"""

DECK_NEW = """        for id in starting_deck {
            state.push_card(id)?;
        }
        // \u00a7189 `A10`: \u5728\u5f00\u5c40\u724c\u7ec4\u91cc\u585e\u4e00\u5f20 Ascender's Bane\u3002\u5b83\u5728\u724c\u7ec4\u5c3e\u5c14\uff08\u4e0e\u5176\u4ed6"\u5f00\u5c40\u724c\u201d\u4e00\u81f4\uff09\u3002
        if ascension >= A_START_CURSE {
            state.push_card(ASCENDERS_BANE)?;
        }
        state.check_invariants()?;"""

# ---------------------------------------------------------------- A20: the second boss

BOSS_ANCHOR = """        if self.act >= MAX_ACT {
            // The last act's boss: the run is won.
            self.boss_beaten = true;
            return;
        }"""

BOSS_NEW = """        if self.act >= MAX_ACT {
            // \u00a7189 `A20`\uff1a\u6700\u540e\u4e00\u5e55\u8981**\u4e24\u4e2a** Boss\u3002\u7b2c\u4e00\u4e2a\u5012\u4e0b\u540e\u8282\u70b9\u91cd\u65b0\u53ef\u6253\uff08\u6e05 `resolved`\uff09\uff0c
            // \u76f4\u5230\u7b2c\u4e8c\u4e2a\u4e5f\u5012\u4e0b\u624d\u7b97\u8d62\u3002\u5956\u52b1\u5c4f\u7167\u65e7\u7ed9\u4e24\u6b21\uff1a\u6bcf\u4e00\u4e2a Boss \u90fd\u662f\u4e00\u573a\u771f\u7684\u6218\u6597\u3002
            if self.at_least(A_DOUBLE_BOSS) && self.bosses_fought == 0 {
                self.bosses_fought = 1;
                // The node has to be fightable again: the caller's only way in is "the cursor is on
                // the boss and the node is not resolved".
                self.resolved = [0; 2];
                self.pending = Pending::None;
                return;
            }
            // The last act's boss: the run is won.
            self.boss_beaten = true;
            return;
        }"""

ADVANCE_ANCHOR = """        self.pending = Pending::None;
        self.resolved = [0; 2];
        self.boss_beaten = false;"""

ADVANCE_NEW = """        self.pending = Pending::None;
        self.resolved = [0; 2];
        self.boss_beaten = false;
        // \u00a7189\uff1a\u6362\u5e55\u91cd\u7f6e"\u8fd9\u4e00\u5e55\u6253\u4e86\u51e0\u4e2a Boss"\u3002
        self.bosses_fought = 0;"""

# ---------------------------------------------------------------- A12: upgraded rewards

CHANCE_FN_ANCHOR = """pub fn reward_bands(kind: FightKind, offset: i32) -> (i32, i32) {"""

CHANCE_FN = '''/// §189 `A12`: 这张奖励牌有多大比例是**升级版**（百分比，整数）。
///
/// 基线（wiki `Card Rewards`）：第一幕 **0%**，第二幕 **12%**，第三幕 **25%**。
/// A12 是 "Upgraded cards are less common" ⇒ **减半**（6% / 12%）。
///
/// ⚠️ 基线这条规则以前**根本不存在** —— 我们的奖励屏从没见过升级牌，而 `inv:§3.5` 那句
/// "第一幕不出现升级牌" 被实现成了"哪一幕都不出现"。所以 A12 是把两条一起做掉。
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

pub fn reward_bands(kind: FightKind, offset: i32) -> (i32, i32) {'''

CARD_ANCHOR = """            used[index] = true;
            cards[slot] = RunId::new(card_pool[index].id).map_err(|_| RunError::BadId)?;"""

CARD_NEW = """            used[index] = true;
            // \u00a7189 `A12`\uff1a\u5148\u62ff\u57fa\u7840\u724c\uff0c\u518d\u6309\u6982\u7387\u6362\u6210\u5b83\u7684 `+` \u884c\u3002\u6982\u7387\u7531**\u5e55 + \u96be\u5ea6**\u51b3\u5b9a
            // （`upgrade_chance_percent`）\uff1b\u6ca1\u6709 `+` \u884c\u7684\u724c\u5c31\u4fdd\u6301\u539f\u6837\uff0c**\u4e0d\u62a5\u9519** \u2014\u2014\u90a3\u662f\u5185\u5bb9\u7684\u4e8b\uff08\u5185\u5bb9\u95e8
            // \u53e6\u6709\u4e00\u6761"\u6bcf\u5f20\u53ef\u5347\u7ea7\u724c\u90fd\u5fc5\u987b\u6709 `+` \u884c"\u7684\u5224\u636e\uff09\u3002
            let mut chosen = card_pool[index].id;
            let chance = upgrade_chance_percent(self.act, self.ascension());
            if chance > 0 && self.rng.roll(RunStream::Reward, 100)? < chance as u32 {
                if let Some(upgraded) = upgraded_id(card_pool, chosen) {
                    chosen = upgraded;
                }
            }
            cards[slot] = RunId::new(chosen).map_err(|_| RunError::BadId)?;"""

HELPER_ANCHOR = """/// §189 `A12`"""

HELPER = '''/// `id` 的 `+` 行，**如果池子里有**（§189）。
///
/// 不做字符串拼接再查表：`PoolCard` 的 id 是 `&'static str`，一次线性扫描比"拼一个 String 再比"
/// 更容易看出它到底在找什么（而且这个池子最多几十条）。
#[must_use]
fn upgraded_id<'a>(pool: &[PoolCard<'a>], base: &str) -> Option<&'a str> {
    pool.iter()
        .map(|card| card.id)
        .find(|id| id.len() == base.len() + 1 && id.starts_with(base) && id.ends_with('+'))
}

/// §189 `A12`'''


def patch(edits):
    text = io.open(PATH, encoding="utf-8").read()
    for old, new in edits:
        if new in text:
            print("  already applied")
            continue
        assert text.count(old) == 1, (text.count(old), old[:60])
        text = text.replace(old, new)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("patched state.rs")


patch([
    (DECK_ANCHOR, DECK_NEW),
    (BOSS_ANCHOR, BOSS_NEW),
    (ADVANCE_ANCHOR, ADVANCE_NEW),
    (CHANCE_FN_ANCHOR, CHANCE_FN),
    (CARD_ANCHOR, CARD_NEW),
])
