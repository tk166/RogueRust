"""§162: `RunState::validate` —— 整局的不变量,以及存档在提交前问它。

The review's item 1: "建立整局状态不变量验证 … 畸形或自相矛盾的存档在提交前被拒绝". The
invariants are the ones the run layer already relies on (spec `run-layer.md` §6.2) plus the ones this
round's bugs proved matter:

* **`len` 之后必须是 EMPTY**（§161.10 的 `remove_card` 尾槽就是这个漏的）—— now *checked on load*,
  so a hand-made archive cannot smuggle state that no writer would produce;
* relics are **unique** (a duplicate would be two of the same relic paying twice);
* `potions_len <= potion_slots()` (Potion Belt raises the slots; 5 potions without it is illegal);
* `floor`/`node` coherence (the cursor is on the map or on the boss sentinel, and the floor agrees);
* `pending` matches the room it is standing in.

⚠️ 与 `run-layer.md` §6.2 的一处差异，写在这里而不是悄悄改规格书：那一条写"0 < floor <= 17"，
因为规格书按"15 行地图 + 16 Boss + 17 Boss 宝箱"描述；**实现里 Boss 是第 16 层的哨兵、没有 17 层**
（`map::BOSS_NODE`、`ROWS = 15`）。校验器按实现写，并在注释里点名这条差异。
"""
import io

PATH = "kernel/rd-run/src/state.rs"

VALIDATE = '''
    /// **这一局自相矛盾吗？**（§162，REVIEW §六 第 4 步的 P1）
    ///
    /// 判据全部是运行层自己已经依赖的东西，而不是新发明的规则 —— 所以"真人打得出来的局面"
    /// 必然通过（`a_real_run_validates_at_every_step` 走一整幕、每一步都问一次）。
    ///
    /// 它存在的理由是**存档**：`archive::restore` 先解码到一个本地状态，再问这一句，全过才提交。
    /// CRC 只能证明"没被改坏"，证明不了"这样的一局可能存在"。
    ///
    /// 与 `run-layer.md` §6.2 第 1 条的差异：规格书写 `0 < floor <= 17`（15 行地图 + 16 Boss +
    /// 17 Boss 宝箱），而实现里 Boss 是第 16 层的哨兵、没有 17 层 ⇒ 这里的上界是 `ROWS + 1`。
    pub fn validate(&self) -> Result<(), RunError> {
        // ---- 标量 -------------------------------------------------------------------------
        if self.health_max <= 0 {
            return Err(RunError::Invariant("health_max must be positive"));
        }
        if self.health < 0 || self.health > self.health_max {
            return Err(RunError::Invariant("health must be in 0..=health_max"));
        }
        if self.gold < 0 {
            return Err(RunError::Invariant("gold must not be negative"));
        }
        if self.removed_cards < 0 {
            return Err(RunError::Invariant("removed_cards must not be negative"));
        }
        if self.act == 0 || self.act > MAX_ACTS {
            return Err(RunError::Invariant("act must be in 1..=MAX_ACTS"));
        }
        if self.ascension > MAX_ASCENSION {
            return Err(RunError::Invariant("ascension must be in 0..=MAX_ASCENSION"));
        }
        if self.potion_chance < 0 || self.potion_chance > 100 {
            return Err(RunError::Invariant("potion_chance must be a percentage"));
        }
        if self.rarity_offset < RARITY_OFFSET_START || self.rarity_offset > RARITY_OFFSET_CAP {
            return Err(RunError::Invariant("rarity_offset is outside its pity band"));
        }

        // ---- 游标与楼层 -------------------------------------------------------------------
        let top = crate::map::ROWS as i32 + 1;
        if self.floor < 0 || self.floor > top {
            return Err(RunError::Invariant("floor must be in 0..=ROWS+1"));
        }
        if self.node < 0 {
            // 「还没出发」：楼层必须是 0，而且没有问句（`?` 房之前什么都没有）。
            if self.floor != 0 {
                return Err(RunError::Invariant("no cursor means floor 0"));
            }
        } else {
            let node = u8::try_from(self.node)
                .map_err(|_| RunError::Invariant("cursor is not a node index"))?;
            if node == crate::map::BOSS_NODE {
                if self.floor != top {
                    return Err(RunError::Invariant("the boss sentinel is the floor past the map"));
                }
            } else {
                let (row, _) = self
                    .map
                    .locate(node)
                    .ok_or(RunError::Invariant("cursor is not on the map"))?;
                if self.floor != row as i32 + 1 {
                    return Err(RunError::Invariant("floor disagrees with the cursor's row"));
                }
            }
        }
        // 已结算位图只许指向地图上的节点（哨兵与越界位都不算）。
        for word in 0..self.resolved.len() {
            let mut bits = self.resolved[word];
            while bits != 0 {
                let bit = bits.trailing_zeros() as usize;
                bits &= bits - 1;
                let index = word * 64 + bit;
                if index >= self.map.node_count() {
                    return Err(RunError::Invariant("a resolved bit points off the map"));
                }
            }
        }

        // ---- 三个定容容器：`len` 之前有内容、之后是空的 -------------------------------------
        if self.deck_len as usize > MAX_RUN_DECK {
            return Err(RunError::Invariant("deck_len exceeds the deck capacity"));
        }
        for (index, card) in self.deck.iter().enumerate() {
            let used = index < self.deck_len as usize;
            if used && card.as_str().is_empty() {
                return Err(RunError::Invariant("a deck slot inside len is empty"));
            }
            if !used && !card.as_str().is_empty() {
                // §161.10：`remove_card` 曾经把被删的牌留在这里，而存档只写前 `len` 项。
                return Err(RunError::Invariant("a deck slot past len is not empty"));
            }
        }
        if self.relics_len as usize > MAX_RUN_RELICS {
            return Err(RunError::Invariant("relics_len exceeds the relic capacity"));
        }
        for (index, relic) in self.relics.iter().enumerate() {
            let used = index < self.relics_len as usize;
            if used && relic.as_str().is_empty() {
                return Err(RunError::Invariant("a relic slot inside len is empty"));
            }
            if !used && !relic.as_str().is_empty() {
                return Err(RunError::Invariant("a relic slot past len is not empty"));
            }
        }
        // 遗物不重复：重复的一件会付两次钱。
        for (index, relic) in self.relics.iter().take(self.relics_len as usize).enumerate() {
            if self.relics[..index].contains(relic) {
                return Err(RunError::Invariant("the same relic is held twice"));
            }
        }
        if self.potions_len > self.potion_slots() {
            // Potion Belt 才是格数的来源（§157）：没有它就装不下第 4、5 瓶。
            return Err(RunError::Invariant("more potions than the belt has slots"));
        }
        for (index, potion) in self.potions.iter().enumerate() {
            let used = index < self.potions_len as usize;
            if used && potion.as_str().is_empty() {
                return Err(RunError::Invariant("a potion slot inside len is empty"));
            }
            if !used && !potion.as_str().is_empty() {
                return Err(RunError::Invariant("a potion slot past len is not empty"));
            }
        }

        // ---- 问句必须与它站着的房间一致 ------------------------------------------------------
        if self.blessing_follow.is_some() && self.pending != Pending::BlessingCard {
            return Err(RunError::Invariant("a blessing follow-up without its question"));
        }
        if self.event_follow.is_some() && self.pending != Pending::EventCard {
            return Err(RunError::Invariant("an event follow-up without its question"));
        }
        if self.start_offers[0] as usize >= START_OFFERS.len()
            || self.start_offers[1] as usize >= START_OFFERS.len()
        {
            return Err(RunError::Invariant("a rolled blessing is not in the table"));
        }
        if self.pending == Pending::Start && self.floor != 0 {
            return Err(RunError::Invariant("the blessing screen exists only before floor 1"));
        }
        if self.pending == Pending::Event && self.event.as_str().is_empty() {
            return Err(RunError::Invariant("an event screen without an event"));
        }
        if let Some(room) = self.pending.room() {
            // Boss 是哨兵，它的"房间类型"由楼层决定（§161.8 的路由就是这么走的）。
            let here = self.node_at_cursor();
            if here != Some(room) {
                return Err(RunError::Invariant("the pending screen is not this room"));
            }
        }

        // ---- 商店与奖励屏 -------------------------------------------------------------------
        for offer in self.shop.cards.iter().take(self.shop.cards_len as usize) {
            if offer.price < 0 || offer.id.as_str().is_empty() {
                return Err(RunError::Invariant("a shop card row is not a live offer"));
            }
        }
        for offer in self.shop.relics.iter().take(self.shop.relics_len as usize) {
            if offer.price < 0 || offer.id.as_str().is_empty() {
                return Err(RunError::Invariant("a shop relic row is not a live offer"));
            }
        }
        if self.reward.cards_len as usize > MAX_REWARD_CARDS || self.reward.gold < 0 {
            return Err(RunError::Invariant("the reward screen is malformed"));
        }
        Ok(())
    }

    /// 游标下这个节点的**类型**；哨兵按 Boss 算，还没出发就是 `None`。
    ///
    /// `NodeKind::Boss` 在生成器里从不赋值（Boss 是地图外的哨兵），所以"类型"必须由这里回答，
    /// 而不是去地图里找 —— 那是 §161.8 的路由器踩过的同一件事。
    #[must_use]
    pub fn node_at_cursor(&self) -> Option<NodeKind> {
        let node = u8::try_from(self.node).ok()?;
        if node == crate::map::BOSS_NODE {
            return Some(NodeKind::Boss);
        }
        let (row, local) = self.map.locate(node)?;
        self.map.row(row)?.node(local).map(|node| node.kind)
    }
'''

# `Pending::room()`：问句对应的房间类型。Reward 没有单一类型（战斗/精英/Boss 都可能），
# 所以它返回 None —— 由 `validate` 不检查它，而不是猜一个。
PENDING_ROOM = '''
impl Pending {
    /// 这个问句只可能出现在哪种房间里？`None` = 不限定（战斗奖励可能在三种战斗节点之后）。
    #[must_use]
    pub const fn room(self) -> Option<NodeKind> {
        Some(match self {
            Self::Rest => NodeKind::Rest,
            Self::Shop => NodeKind::Shop,
            Self::Chest => NodeKind::Treasure,
            Self::Event | Self::EventCard => NodeKind::Unknown,
            Self::None | Self::Reward | Self::Start | Self::BlessingCard => return None,
        })
    }
}
'''

MAX_ACTS = '''
/// 一局最多几幕（三幕 Boss 之后结束）。
pub const MAX_ACTS: u8 = 3;
'''


def main():
    text = io.open(PATH, encoding="utf-8").read()
    assert "pub fn validate(&self)" not in text, "already inserted"
    assert "pub const MAX_ACTS" not in text, "MAX_ACTS already there"

    # MAX_ACTS next to MAX_ASCENSION
    anchor = "pub const MAX_ASCENSION: u8 = 20;"
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + MAX_ACTS)

    # `Pending::room()` after the Pending enum's closing brace — anchor on the impl that follows it
    anchor2 = "impl Pending {"
    if text.count(anchor2) == 0:
        # insert right before the first `impl RunState`
        anchor2 = "impl RunState {"
        assert text.count(anchor2) == 1
        text = text.replace(anchor2, PENDING_ROOM.strip() + "\n\n" + anchor2)
    else:
        raise SystemExit("Pending already has an impl; merge room() into it by hand")

    # `validate` + `node_at_cursor` at the end of `impl RunState` (before the test module)
    anchor3 = "impl RunState {"
    assert text.count(anchor3) == 1
    idx = text.index(anchor3)
    end = text.index("\n}\n", idx)
    text = text[:end] + "\n" + VALIDATE + text[end:]

    io.open(PATH, "w", encoding="utf-8", newline="").write(text)
    print("RunState::validate + node_at_cursor + Pending::room + MAX_ACTS")


if __name__ == "__main__":
    main()
