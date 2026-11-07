"""§259 第 3 层：`campfire_options()` + `lift` / `toke` / `dig` / `recall`。

wiki（`Rest Sites` 页）的三组选项，落成**六个布尔**（谁可用），四个动作各自把 `Pending::Rest` 收掉。

三条设计决定，都是从"哪种写错看不出来"倒推的：

1. **选项是算出来的，不是存下来的**（`campfire_options` 每次现算）。存一份布尔表就会与
   "现在持有哪些遗物 / 力量用了几次 / 牌组还有没有可升的牌"漂移，而漂移在界面上只表现为
   "一个灰按钮突然能点"。
2. **`toke` 与商店删牌共用同一段搬移**（`remove_deck_card`），但**不收钱** —— 它是一次篝火选项，
   不是服务。所以把搬移抽出来、让两处都调它，而不是复制一份（复制的那份一定会漏 `marks`）。
3. **`dig` 只抽 Common/Uncommon/Rare**（wiki 原话："只给 Common/Uncommon/Rare"）。过滤放在
   **抽之前**（构造候选池），不是在抽到之后重抽 —— 重抽会让"池子里只有 Event 遗物"变成死循环。
"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'

MARKER = '''    /// Declare what the node under the cursor needs.'''

NEW = r'''    /// §259：篝火上有哪些选项（wiki `Rest Sites`）。
    ///
    /// 六个布尔**现算**，不缓存：它们各自依赖不同的运行期状态（持有哪些遗物、`Girya` 用了几次、
    /// 牌组里还有没有可升的牌、当前幕有没有拿过红钥匙）。存一份就会与真实状态漂移，而漂移在
    /// 界面上只表现为"一个本该灰掉的按钮能点"。
    ///
    /// | 选项 | 谁给的 | 灰掉的条件（wiki） |
    /// |---|---|---|
    /// | Rest | 默认 | `Coffee Dripper` / `Mark of the Bloom`；**满血也能用** |
    /// | Smith | 默认 | `Fusion Hammer`；**全升完** |
    /// | Recall | 默认 | 本幕已经拿过红钥匙（`ruby_key`） |
    /// | Lift | `Girya` | 已经用满 3 次 |
    /// | Toke | `Peace Pipe` | 牌组空 |
    /// | Dig | `Shovel` | 从不（总是可用） |
    #[must_use]
    pub fn campfire_options(&self) -> CampfireOptions {
        let mut options = CampfireOptions {
            rest: true,
            smith: true,
            // §259：红钥匙一局只有一把；拿到之后 Recall 就没了（wiki："if you have not already
            // obtained the Ruby Key this act"）。
            recall: !self.ruby_key,
            lift: false,
            toke: self.deck_len > 0,
            dig: false,
        };
        for slot in 0..self.relics_len as usize {
            match Self::relic_effect(self.relics[slot].as_str()) {
                Some(RelicEffect::NoRest) => options.rest = false,
                Some(RelicEffect::NoSmith) => options.smith = false,
                Some(RelicEffect::CampfireLift) => {
                    options.lift = self.girya_lifts < GIRYA_MAX_LIFTS;
                }
                Some(RelicEffect::CampfireToke) => {}
                Some(RelicEffect::CampfireDig) => options.dig = true,
                // 其余遗物不改变选项集合 —— 列出来是为了让"新增一个变体"在这里编译报错。
                Some(
                    RelicEffect::EndOfCombatHeal(_)
                    | RelicEffect::EndOfCombatHealIfBelow { .. }
                    | RelicEffect::MaxHealthUp(_)
                    | RelicEffect::HealUp(_)
                    | RelicEffect::StartCombatBlock(_)
                    | RelicEffect::StartCombatStatus(_, _)
                    | RelicEffect::StartCombatStatusOnEnemies(_, _)
                    | RelicEffect::RestHealBonus(_)
                    | RelicEffect::RestHealPerFiveCards(_)
                    | RelicEffect::FightGoldPercent(_)
                    | RelicEffect::ExtraPotionSlots(_)
                    | RelicEffect::RestCardReward,
                )
                | None => {}
            }
        }
        // "全升完 ⇒ Smith 灰掉"：`+` 行在内容里是**另一张卡**，所以"能不能升"要看
        // "这张牌的 id 加上 `+` 之后是不是同一张卡" —— 但运行层不认识内容，所以判据只能是
        // "牌组里有没有一个不带 `+` 的 id"。这与 `upgraded_id` 的来路（调用方给的映射）一致。
        let mut upgradable = false;
        for slot in 0..self.deck_len as usize {
            if !self.deck[slot].as_str().ends_with('+') {
                upgradable = true;
                break;
            }
        }
        options.smith = options.smith && upgradable;
        options
    }

    /// §259：`Lift`（`Girya`）—— 力量 +1 的上限记一次，**当回合不回血、不给状态**。
    ///
    /// 力量从**下一场战斗开始**起生效，并且之后每场都带（`combat_bonus` 按 `girya_lifts` 折算）。
    /// 用满 3 次之后这一步是 `WrongPhase`（选项已经不在列表里了，走到这里说明调用方在猜）。
    pub fn lift(&mut self) -> Result<u8, RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if self.girya_lifts >= GIRYA_MAX_LIFTS {
            return Err(RunError::WrongPhase);
        }
        if !self.holds_relic_effect(RelicEffect::CampfireLift) {
            return Err(RunError::UnsupportedRelic { index: 0 });
        }
        self.girya_lifts += 1;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(self.girya_lifts)
    }

    /// §259：`Toke`（`Peace Pipe`）—— 从牌组里删一张，**不收钱**。
    pub fn toke(&mut self, card: usize) -> Result<(), RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if !self.holds_relic_effect(RelicEffect::CampfireToke) {
            return Err(RunError::UnsupportedRelic { index: 0 });
        }
        self.remove_deck_card(card)?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// §259：`Dig`（`Shovel`）—— 抽一件遗物，**候选池只含 Common/Uncommon/Rare**。
    ///
    /// `relic_pool` 是调用方给的**全量**池（含 Boss/Shop/Event）；过滤在这里做，因为"哪些稀有度
    /// 能被抽到"是规则，而"内容里有哪些遗物"是内容。
    pub fn dig(&mut self, relic_pool: &[PoolRelic<'_>]) -> Result<RunId, RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if !self.holds_relic_effect(RelicEffect::CampfireDig) {
            return Err(RunError::UnsupportedRelic { index: 0 });
        }
        let mut candidates = [PoolRelic {
            id: "",
            rarity: Rarity::Common,
        }; MAX_POOL];
        let mut count = 0usize;
        for entry in relic_pool {
            if matches!(entry.rarity, Rarity::Common | Rarity::Uncommon | Rarity::Rare) {
                if count >= candidates.len() {
                    return Err(RunError::Capacity);
                }
                candidates[count] = *entry;
                count += 1;
            }
        }
        let relic = self.pick_relic(RunStream::Relic, &candidates[..count])?;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(relic)
    }

    /// §259：`Recall` —— 拿红钥匙（Act 4 的门票）。
    pub fn recall(&mut self) -> Result<(), RunError> {
        if self.pending != Pending::Rest {
            return Err(RunError::WrongPhase);
        }
        if self.ruby_key {
            return Err(RunError::WrongPhase);
        }
        self.ruby_key = true;
        self.pending = Pending::None;
        self.mark_resolved();
        Ok(())
    }

    /// §259：这件遗物在不在腰上、以及它的效果是不是 `wanted`（`Copy` 比较，因为变体都是无载荷
    /// 的单元变体）。
    fn holds_relic_effect(&self, wanted: RelicEffect) -> bool {
        for slot in 0..self.relics_len as usize {
            if Self::relic_effect(self.relics[slot].as_str()) == Some(wanted) {
                return true;
            }
        }
        false
    }

'''

EDITS = [
    # 1) 抽出来的"从牌组删一张"（toke 与商店共用，不收钱）
    ('''    pub fn remove_card(&mut self, card: usize) -> Result<i32, RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        // §189 `A10`：Ascender's Bane 的卡面写着 "Cannot be removed"，StS 也把这一条写在这张卡
        // 自己的代码里。拒绝发生在**扣钱之前**，所以"拒绝 ⇒ 一个字节都不改"。
        if self.deck[card].as_str() == ASCENDERS_BANE {
            return Err(RunError::CannotRemove);
        }
        let price = self.remove_card_price();
        if self.gold < price {
            return Err(RunError::NotEnoughGold {
                price,
                gold: self.gold,
            });
        }
        self.adjust_gold(-price);
        // Shift the tail down; deck order is observable, so the order of the survivors is kept.
        for index in card..(self.deck_len as usize - 1) {
            self.deck[index] = self.deck[index + 1];
            // §253：**mark 跟着牌走**。漏了这一行就会出现"删掉一张牌，另一张继承了它的伤害" ——
            // 而那在页面上完全看不出来（两张牌都还在，只是数字变了）。
            self.marks[index] = self.marks[index + 1];
        }
        // **`len` 之后必须是 EMPTY**，与 `Bounded` 的不变式同一条（REVIEW P1，§161.10）。
        // 少了这一行，被删的那张牌仍留在尾槽里：`deck()` 看不见它，但**结构相等看不见的是另一回事**
        // —— 存档只写前 `len` 项，于是"删过牌的局"回档后与原局不相等，而 round-trip 测试查不出来
        // （它从来不在删牌之后存档）。`drop_potion` 早就是这么写的，是这一个兄弟漏了。
        self.deck[self.deck_len as usize - 1] = RunId::EMPTY;
        self.deck_len -= 1;
        self.removed_cards += 1;
        Ok(price)
    }''',
     '''    pub fn remove_card(&mut self, card: usize) -> Result<i32, RunError> {
        if self.pending != Pending::Shop {
            return Err(RunError::WrongPhase);
        }
        let price = self.remove_card_price();
        if self.gold < price {
            return Err(RunError::NotEnoughGold {
                price,
                gold: self.gold,
            });
        }
        // §259：**先搬再扣钱之前先验**（`remove_deck_card` 里的两条拒绝：越界、Ascender's Bane）
        // 仍在扣钱之前 —— 顺序与原来一致，所以"拒绝 ⇒ 一个字节都不改"照旧成立。
        self.remove_deck_card(card)?;
        self.adjust_gold(-price);
        Ok(price)
    }

    /// §259：从牌组里删掉第 `card` 张（**不收钱、不改 `removed_cards`**）。
    ///
    /// 商店（`remove_card`）与篝火的 `Toke` 共用这一段。抽出来是因为**复制的那一份一定会漏
    /// `marks`**：§253 已经在同一个循环里踩过一次（"删掉一张牌，另一张继承了它的伤害"，
    /// 页面上完全看不出来）。
    fn remove_deck_card(&mut self, card: usize) -> Result<(), RunError> {
        if card >= self.deck_len as usize {
            return Err(RunError::BadCard(card as u8));
        }
        // §189 `A10`：Ascender's Bane 的卡面写着 "Cannot be removed"，StS 也把这一条写在这张卡
        // 自己的代码里。
        if self.deck[card].as_str() == ASCENDERS_BANE {
            return Err(RunError::CannotRemove);
        }
        // Shift the tail down; deck order is observable, so the order of the survivors is kept.
        for index in card..(self.deck_len as usize - 1) {
            self.deck[index] = self.deck[index + 1];
            // §253：**mark 跟着牌走**。
            self.marks[index] = self.marks[index + 1];
        }
        // **`len` 之后必须是 EMPTY**（REVIEW P1，§161.10）。
        self.deck[self.deck_len as usize - 1] = RunId::EMPTY;
        self.deck_len -= 1;
        Ok(())
    }'''),
    # 2) `campfire_options` 与四个动作插在 `begin_node` 之前
    (MARKER, NEW + MARKER),
]


def main():
    src = io.open(STATE, encoding='utf-8').read()
    for old, new in EDITS:
        assert src.count(old) == 1, (src.count(old), old[:60])
        src = src.replace(old, new)
    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(src)
    print('layer 3: campfire options + 4 actions')


main()
