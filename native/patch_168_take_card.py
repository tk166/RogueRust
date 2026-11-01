"""§161.8: `take_card` must not close the reward screen.

Found by the vertical slice, not by a unit test: on an elite's reward screen the driver took the
**card** first (that is what a player does) and the relic and potion rows disappeared with it --
`take_card` set `pending = None; mark_resolved()`, while `take_relic` / `take_potion` only cleared
their own row.

In StS the three rows are independent: you take any of them in any order, and the screen closes when
you leave. The asymmetry inside this one function *was* the bug: two of the three take-one-row
siblings behaved correctly.
"""
import io

PATH = "kernel/rd-run/src/state.rs"


def main():
    text = io.open(PATH, encoding="utf-8").read()

    old = """    /// Take card `slot` from the reward screen and leave it.
    pub fn take_card(&mut self, slot: usize) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let Some(id) = self.reward.cards().get(slot).copied() else {
            return Err(RunError::EmptyOffer(slot as u8));
        };
        if id == RunId::EMPTY {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(id.as_str())?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }"""

    new = """    /// Take card `slot` from the reward screen. **The screen stays open** (§161.8).
    ///
    /// The card, the potion and the relic are three independent rows of one screen: taking the card
    /// must not take the other two with it. This used to set `pending = None; mark_resolved()`,
    /// which meant a player who took the card first **lost the elite's relic** -- and nothing said
    /// so, because the relic row simply vanished with the screen.
    ///
    /// §161.8's vertical slice found it the honest way: its elite scenario took the card (the first
    /// thing a player does) and then asked where the relic went. `take_relic` / `take_potion` were
    /// already correct, so the bug was the asymmetry inside this one function.
    ///
    /// The node is settled by `skip_reward` (or by `leave`), which is also the way out when every
    /// row has been taken.
    pub fn take_card(&mut self, slot: usize) -> Result<(), RunError> {
        if self.pending != Pending::Reward {
            return Err(RunError::WrongPhase);
        }
        let Some(id) = self.reward.cards().get(slot).copied() else {
            return Err(RunError::EmptyOffer(slot as u8));
        };
        if id == RunId::EMPTY {
            return Err(RunError::EmptyOffer(slot as u8));
        }
        self.push_card(id.as_str())?;
        // Blank the row, keep the screen: the other two rows are still on the table.
        self.reward.cards[slot] = RunId::EMPTY;
        Ok(())
    }"""

    assert text.count(old) == 1, text.count(old)
    io.open(PATH, "w", encoding="utf-8", newline="").write(text.replace(old, new))
    print("take_card keeps the reward screen open")


if __name__ == "__main__":
    main()
