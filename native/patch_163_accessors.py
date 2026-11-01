"""§163.1: the accessors `run_hash` needs (and the two read-only views the replay will want).

They are `pub` **reads** on a struct whose fields are private — the same shape every other reader in
this crate uses. Nothing here mutates, so the archive's "write through the same crate" rule stands.
"""
import io

PATH = "kernel/rd-run/src/state.rs"

ACCESSORS = '''
    /// 当前的药水掉率（§157：40 起、每次战后 ±10、换幕重置）。
    #[must_use]
    pub const fn potion_chance(&self) -> i32 {
        self.potion_chance
    }

    /// `?` 房的三条累计计数（`inv:§7.5`），换幕重置。
    #[must_use]
    pub const fn unknown(&self) -> &[i32; 3] {
        &self.unknown
    }

    /// 已经选定的祝福后续动作（只在 `Pending::BlessingCard` 期间非空）。
    #[must_use]
    pub const fn blessing_follow(&self) -> Option<BlessingFollowUp> {
        self.blessing_follow
    }

    /// 已选定的事件后续动作（只在 `Pending::EventCard` 期间非空）。
    #[must_use]
    pub const fn event_follow(&self) -> Option<DeckChange> {
        self.event_follow
    }

    /// 已结算位图的两个字（节点的下标 → 位）。
    #[must_use]
    pub const fn resolved_words(&self) -> &[u64; 2] {
        &self.resolved
    }

    /// 商店的卡位（含已买走/未上架的行，`price < 0`）。
    #[must_use]
    pub fn shop_cards(&self) -> &[Offer] {
        &self.shop.cards
    }

    /// 商店的遗物位。
    #[must_use]
    pub fn shop_relics(&self) -> &[Offer] {
        &self.shop.relics
    }

    /// 商店卡位的有效行数（槽位下标必须稳定，所以它不随购买减少）。
    #[must_use]
    pub const fn shop_cards_len(&self) -> u8 {
        self.shop.cards_len
    }

    /// 商店遗物位的有效行数。
    #[must_use]
    pub const fn shop_relics_len(&self) -> u8 {
        self.shop.relics_len
    }

    /// 奖励屏的三张卡（空槽是 `EMPTY`）。
    #[must_use]
    pub fn reward_cards(&self) -> &[RunId] {
        &self.reward.cards[..self.reward.cards_len as usize]
    }
'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert "pub const fn potion_chance" not in text, "already inserted"
    anchor = "    /// The Ascension level this run is played at (`0` = none, §159)."
    assert text.count(anchor) == 1, text.count(anchor)
    io.open(PATH, "w", encoding="utf-8", newline="").write(
        text.replace(anchor, ACCESSORS + "\n" + anchor)
    )
    print("ten accessors added")
    print("note: start_offers() returns [StartOffer; 2] by value -- callers must not deref")


if __name__ == "__main__":
    main()
