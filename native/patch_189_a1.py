"""§189: A1 / A10 / A12 / A20 -- the four run-layer rules that were left.

Each is one number or one branch that already had a home:

| rule | wiki | where it lands |
|---|---|---|
| **A1** | "Elites are more common" (8% -> 16%, paid for by the combat share) | `map.rs`: the 53/8/12/5/22 roll table becomes level-aware |
| **A10** | "Start with Ascender's Bane" (a Curse that cannot be removed) | `RunState::new_with_ascension` appends it; `remove_card` refuses it |
| **A12** | "Upgraded cards are less common" (halved in acts 2-3) | `roll_reward`: the base rule (12% / 25% by act) had never been implemented, so both halves land here |
| **A20** | "Fight two bosses in Act 3" | `mark_boss_beaten`: the first boss leaves the node fightable again |

`at_least` stays the only comparison: every threshold is a constant in the `A_*` block.
"""
import io
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def patch(rel, edits, label):
    path = os.path.join(ROOT, rel)
    text = io.open(path, encoding="utf-8").read()
    for old, new in edits:
        if new in text:
            print("  already applied:", label)
            continue
        assert text.count(old) == 1, (label, text.count(old), old[:70])
        text = text.replace(old, new)
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("patched", rel)


# ============================================================ the three constants

STATE = "kernel/rd-run/src/state.rs"
patch(STATE, [
    (
        """/// \u00a7188\uff1a\u4e8b\u4ef6\u53d8\u5f97\u66f4\u7cdf\uff08wiki: *Unfavorable Events \u2014 many events have less positive outcomes
/// and more severe consequences*\uff09\u3002\u5185\u5bb9\u7528 `Effects*Asc` \u7ed9\u51fa\u53d8\u4f53\uff1b\u6ca1\u6709\u53d8\u4f53\u7684\u9009\u9879\u7167\u65e7\u3002
pub const A_EVENTS_WORSE: u8 = 15;""",
        """/// \u00a7188\uff1a\u4e8b\u4ef6\u53d8\u5f97\u66f4\u7cdf\uff08wiki: *Unfavorable Events \u2014 many events have less positive outcomes
/// and more severe consequences*\uff09\u3002\u5185\u5bb9\u7528 `Effects*Asc` \u7ed9\u51fa\u53d8\u4f53\uff1b\u6ca1\u6709\u53d8\u4f53\u7684\u9009\u9879\u7167\u65e7\u3002
pub const A_EVENTS_WORSE: u8 = 15;
/// \u00a7189\uff1a\u7cbe\u82f1\u66f4\u5e38\u89c1\uff08wiki: *Elites are more common* \u2014 8% \u2192 16%\uff09\u3002
pub const A_ELITE_MORE: u8 = 1;
/// \u00a7189\uff1a\u5f00\u5c40\u5e26 Ascender's Bane\uff08wiki: *Start with Ascender's Bane*\uff09\u3002
pub const A_START_CURSE: u8 = 10;
/// \u00a7189\uff1a\u5347\u7ea7\u724c\u66f4\u5c11\uff08wiki: *Upgraded cards are less common*\uff09\u2014\u2014 \u4e8c\u4e09\u5e55\u7684\u5347\u7ea7\u6982\u7387\u51cf\u534a\u3002
pub const A_FEWER_UPGRADES: u8 = 12;
/// \u00a7189\uff1a\u7b2c\u4e09\u5e55\u4e24\u4e2a Boss\uff08wiki: *Double Boss*\uff09\u3002
pub const A_DOUBLE_BOSS: u8 = 20;

/// A10 \u7684\u8bc5\u5492\u3002**\u4e0d\u80fd\u88ab\u5220** \u2014\u2014 wiki \u7684\u5361\u9762\u5c31\u5199\u7740 "Cannot be removed"\uff1bStS \u81ea\u5df1\u4e5f\u662f\u628a
/// \u8fd9\u4e00\u6761\u5199\u5728\u8fd9\u5f20\u5361\u7684\u4ee3\u7801\u91cc\uff08\u5b83\u4e0d\u662f\u4e00\u4e2a\u901a\u7528\u6807\u7b7e\uff09\u3002
pub const ASCENDERS_BANE: &str = "ascenders_bane";""",
    ),
], "A constants")

# ============================================================ A1: the map's elite share

MAP = "kernel/rd-run/src/map.rs"
patch(MAP, [
    (
        """/// The 53/8/12/5/22 table (`inv:§7.3`). Cumulative upper bounds, so the mapping is auditable.
#[must_use]
pub const fn kind_for_roll(roll: u32) -> Option<NodeKind> {
    match roll {
        0..=52 => Some(NodeKind::Combat),   // 53%
        53..=60 => Some(NodeKind::Elite),   //  8%
        61..=72 => Some(NodeKind::Rest),    // 12%
        73..=77 => Some(NodeKind::Shop),    //  5%
        78..=99 => Some(NodeKind::Unknown), // 22%
        _ => None,
    }
}""",
        """/// The 53/8/12/5/22 table (`inv:§7.3`). Cumulative upper bounds, so the mapping is auditable.
#[must_use]
pub const fn kind_for_roll(roll: u32) -> Option<NodeKind> {
    kind_for_roll_at(roll, 0)
}

/// `kind_for_roll` **at an ascension level** (§189).
///
/// A1 is "elites are more common": 8% → 16%, and the inventory records that the *combat* share pays
/// for it (53% → 45%). Rest / shop / unknown keep their 12 / 5 / 22, so the table still sums to 100
/// and a reader can audit it by comparing two constants.
#[must_use]
pub const fn kind_for_roll_at(roll: u32, ascension: u8) -> Option<NodeKind> {
    // The only movable boundary is the combat/elite one: everything above it is fixed.
    let combat_top = if ascension >= crate::state::A_ELITE_MORE {
        44
    } else {
        52
    };
    const ELITE_TOP: u32 = 60;
    const REST_TOP: u32 = 72;
    const SHOP_TOP: u32 = 77;
    match roll {
        r if r <= combat_top => Some(NodeKind::Combat),
        r if r <= ELITE_TOP => Some(NodeKind::Elite),
        r if r <= REST_TOP => Some(NodeKind::Rest),
        r if r <= SHOP_TOP => Some(NodeKind::Shop),
        r if r <= 99 => Some(NodeKind::Unknown),
        _ => None,
    }
}""",
    ),
], "A1-table")

print("part 1 done")
