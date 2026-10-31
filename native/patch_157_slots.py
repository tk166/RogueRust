"""§157: the potion drop chance is the wiki's **moving** 40%, not a flat constant.

The wiki (slaythespire.wiki.gg/wiki/Potions, "Sources"):

    The default chance of a potion dropping is 40% and resets at the start of each Act.
    If a potion drops, the chance decreases by 10%. If a potion doesn't drop, the chance
    increases by 10%.

So the flat `POTION_DROP_PERCENT = 40` was wrong in exactly the way that matters over a run: five
fights without a potion must raise the chance to 90%, not keep it at 40%.

Also §157:

* **Potion Belt** (+2 slots) -- the wiki says it is the only way to raise the three slots, so the slot
  count becomes `potion_slots()` instead of the array size. Storage (`MAX_RUN_POTIONS`) grows to 5;
  the *rule* stays "three, or more with the belt".
* **A full belt still rolls**: the wiki notes the roll happens even when the potion is not shown
  (the Colosseum note), so the chance keeps moving; only the **offer** is suppressed.
"""

import io

PATH = r"D:\Vibe\sts-tui\kernel\rd-run\src\state.rs"

with io.open(PATH, encoding="utf-8") as handle:
    source = handle.read()


def replace_once(old, new, why):
    global source
    if old not in source:
        raise SystemExit("anchor missing: " + why)
    source = source.replace(old, new, 1)


# ---- 1. the constants -------------------------------------------------------------------------
replace_once(
    """pub const MAX_RUN_POTIONS: usize = 3;""",
    """/// Belt **storage**: five slots, because `potion_belt` adds two (§157).
///
/// The *rule* is still "three slots" -- that is [`RunState::potion_slots`], and the difference between
/// storage and rule is what lets a relic raise the count without a second array.
pub const MAX_RUN_POTIONS: usize = 5;

/// The wiki's three starting potion slots (§157; Ascension 11's reduction does not exist here).
pub const BASE_POTION_SLOTS: u8 = 3;""",
    "MAX_RUN_POTIONS",
)

replace_once(
    """pub const POTION_DROP_PERCENT: u32 = 40;""",
    """/// The wiki's **starting** potion drop chance (§157). It moves: -10 after a drop, +10 after a
/// miss, reset at the start of each act. A flat 40% was wrong in the way that matters over a run.
pub const POTION_DROP_START: i32 = 40;

/// How much the chance moves per fight (`+10` on a miss, `-10` on a drop).
pub const POTION_DROP_STEP: i32 = 10;""",
    "POTION_DROP_PERCENT",
)

# ---- 2. the field -----------------------------------------------------------------------------
replace_once(
    """    potions: [RunId; MAX_RUN_POTIONS],
    potions_len: u8,""",
    """    potions: [RunId; MAX_RUN_POTIONS],
    potions_len: u8,
    /// The potion drop chance **right now** (§157): starts at 40, `-10` after a drop, `+10` after a
    /// miss, reset when an act starts.
    potion_chance: i32,""",
    "potion_chance field",
)

replace_once(
    """            potions: [RunId::EMPTY; MAX_RUN_POTIONS],
            potions_len: 0,""",
    """            potions: [RunId::EMPTY; MAX_RUN_POTIONS],
            potions_len: 0,
            potion_chance: POTION_DROP_START,""",
    "potion_chance init",
)

# ---- 3. slots = 3 + the belt ------------------------------------------------------------------
replace_once(
    """    /// Add a potion. Past [`MAX_RUN_POTIONS`] this is an error (the belt has three slots).""",
    """    /// The potion drop chance right now (§157).
    #[must_use]
    pub const fn potion_drop_chance(&self) -> i32 {
        self.potion_chance
    }

    /// How many potion slots the run has: three, plus `potion_belt`'s two (§157).
    #[must_use]
    pub fn potion_slots(&self) -> u8 {
        let mut slots = BASE_POTION_SLOTS;
        for slot in 0..self.relics_len as usize {
            if let Some(RelicEffect::ExtraPotionSlots(extra)) =
                Self::relic_effect(self.relics[slot].as_str())
            {
                slots = slots.saturating_add(u8::try_from(extra).unwrap_or(0));
            }
        }
        slots
    }

    /// Is there room for one more potion?
    #[must_use]
    pub fn potion_room(&self) -> bool {
        self.potions_len < self.potion_slots()
    }

    /// Add a potion. Past [`Self::potion_slots`] this is an error (the belt is full).""",
    "potion_slots",
)

replace_once(
    """        let slot = self.potions_len as usize;
        if slot >= MAX_RUN_POTIONS {
            return Err(RunError::Capacity);
        }""",
    """        let slot = self.potions_len as usize;
        if slot >= usize::from(self.potion_slots()) || slot >= MAX_RUN_POTIONS {
            return Err(RunError::Capacity);
        }""",
    "push_potion capacity",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("slots + chance field added")
