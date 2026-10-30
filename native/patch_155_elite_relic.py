"""§155: an elite (and a boss) pays a **relic**, and the reward screen can be taken from.

StS's elite reward is "gold + card choice + a relic"; ours paid gold and cards only. The relic has to
arrive through `push_relic` -- the single grant point §145 established -- so a relic from a fight is
validated and fires its run-level effects exactly like one from a chest or a shop.

Changes, all in `kernel/rd-run/src/state.rs`:

* `Reward` grows `relic: RunId`;
* `roll_reward` takes a `relic_pool: &[&str]` and fills that slot for `Elite`/`Boss` only (a normal
  fight clears it), using the `Reward` stream so the pity offset and the card rolls are untouched;
* `reward_relic()` / `take_relic()` next to the potion pair (`take_relic` refuses when the table has
  none, and reuses `push_relic`, so a full relic list is an error rather than a silent drop);
* `RunError::NoSuchRelic` for "there is no relic on the table".
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


# ---- 1. the field ------------------------------------------------------------------------------
replace_once(
    """    /// The potion this fight dropped, if any (`inv:§9.3`: 40% of fights, and a full belt simply
    /// means the offer cannot be taken).
    potion: RunId,
}""",
    """    /// The potion this fight dropped, if any (`inv:§9.3`: 40% of fights, and a full belt simply
    /// means the offer cannot be taken).
    potion: RunId,
    /// The relic this fight pays (§155). **Only elites and bosses** have one; a normal fight clears
    /// it. StS's elite reward is "gold + cards + a relic", and ours paid the first two.
    relic: RunId,
}""",
    "Reward field",
)

replace_once(
    """            cards_len: 0,
            potion: RunId::EMPTY,
        }
    }""",
    """            cards_len: 0,
            potion: RunId::EMPTY,
            relic: RunId::EMPTY,
        }
    }""",
    "Reward::empty",
)

# ---- 2. roll_reward ----------------------------------------------------------------------------
replace_once(
    """    pub fn roll_reward(
        &mut self,
        card_pool: &[PoolCard<'_>],
        potion_pool: &[&str],
        kind: FightKind,
    ) -> Result<(), RunError> {""",
    """    pub fn roll_reward(
        &mut self,
        card_pool: &[PoolCard<'_>],
        potion_pool: &[&str],
        relic_pool: &[&str],
        kind: FightKind,
    ) -> Result<(), RunError> {""",
    "roll_reward signature",
)

replace_once(
    """        self.reward = Reward {
            gold: paid,
            cards,
            cards_len: MAX_REWARD_CARDS as u8,
            potion,
        };""",
    """        // §155: an elite (and a boss) also pays a relic. The pool is the un-held relic list --
        // `relic_candidates` already de-dupes what the player owns, so a full set means "no relic"
        // rather than "the same relic again". Drawn on the `Reward` stream, after the cards: the
        // card rolls keep their sequence and only the relic's index moves.
        let relic = if matches!(kind, FightKind::Elite | FightKind::Boss) && !relic_pool.is_empty() {
            let index = self.rng.roll(RunStream::Reward, relic_pool.len() as u32)? as usize;
            RunId::new(relic_pool[index]).map_err(|_| RunError::BadId)?
        } else {
            RunId::EMPTY
        };
        self.reward = Reward {
            gold: paid,
            cards,
            cards_len: MAX_REWARD_CARDS as u8,
            potion,
            relic,
        };""",
    "Reward construction",
)

# ---- 3. accessors + taking it ------------------------------------------------------------------
replace_once(
    """    /// Take the potion off the reward table. A **full belt is an error**, not a silent discard:""",
    """    /// The relic this fight pays, or `None` (§155: elites and bosses only).
    #[must_use]
    pub fn reward_relic(&self) -> Option<&str> {
        let id = self.reward.relic.as_str();
        if id.is_empty() {
            None
        } else {
            Some(id)
        }
    }

    /// Take the relic off the reward table.
    ///
    /// Goes through [`Self::push_relic`] -- the single grant point (§145) -- so a fight-won relic is
    /// validated and its run-level effects fire exactly like a chest's. A full relic list is an
    /// **error**, not a silent drop.
    pub fn take_relic(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let id = self.reward.relic;
        if id.as_str().is_empty() {
            return Err(RunError::NoSuchRelic);
        }
        self.push_relic(id.as_str())?;
        self.reward.relic = RunId::EMPTY;
        Ok(())
    }

    /// Take the potion off the reward table. A **full belt is an error**, not a silent discard:""",
    "take_relic",
)

with io.open(PATH, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(source)
print("state.rs patched")

# ---- 4. the error variant ----------------------------------------------------------------------
STREAMS = r"D:\Vibe\sts-tui\kernel\rd-run\src\streams.rs"
with io.open(STREAMS, encoding="utf-8") as handle:
    streams = handle.read()
if "NoSuchRelic" not in streams:
    at = streams.find("NoSuchPotion")
    if at < 0:
        raise SystemExit("NoSuchPotion anchor missing")
    line_start = streams.rfind("\n", 0, at) + 1
    line_end = streams.find("\n", at) + 1
    addition = (
        "    /// `take_relic` on a reward table that has no relic (§155).\n"
        "    NoSuchRelic,\n"
    )
    streams = streams[:line_end] + addition + streams[line_end:]
    with io.open(STREAMS, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(streams)
    print("RunError::NoSuchRelic added")
