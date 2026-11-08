"""§292 Wave 1 第二段：表项 + 四个钩子 + `DeckChange::Duplicate` + 稀有档倍率。"""
import io

STATE = 'D:/Vibe/sts-tui/kernel/rd-run/src/state.rs'


def patch(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:110])
    return text.replace(old, new)


def main():
    s = io.open(STATE, encoding='utf-8').read()

    # ── 1. `relic_effect` 的新表项（挂在 `twisted_funnel` 之后、`_ => None` 之前）
    s = patch(s, '''            "twisted_funnel" => {
                Some(RelicEffect::StartCombatStatusOnEnemies("standard.poison", 4))
            }
            _ => None,''', '''            "twisted_funnel" => {
                Some(RelicEffect::StartCombatStatusOnEnemies("standard.poison", 4))
            }
            // §292 Wave 1：十一件。前两件的"效果"就是"没有效果"。
            "cultist_headpiece" => Some(RelicEffect::Nothing),
            "spirit_poop" => Some(RelicEffect::Nothing),
            "face_of_cleric" => Some(RelicEffect::EndOfCombatMaxHealthUp(1)),
            "matryoshka" => Some(RelicEffect::ChestExtraRelic { chests: 2 }),
            "nloths_hungry_face" => Some(RelicEffect::NextChestEmpty(1)),
            // 第一半是能量（第二半 `ChestAddsCurse` 在 `RELIC_SECOND_HALVES`）。
            "cursed_key" => Some(RelicEffect::StartCombatStatus("standard.cursed_key", 1)),
            "calling_bell" => Some(RelicEffect::PickupCurseAndRelics {
                curse: "curse_of_the_bell",
                relics: 3,
            }),
            "cauldron" => Some(RelicEffect::PickupPotions(5)),
            "dollys_mirror" => Some(RelicEffect::PickupDuplicate(1)),
            "nloths_gift" => Some(RelicEffect::RareCardChanceMultiplier(3)),
            "sacred_bark" => Some(RelicEffect::PotionEffectPercent(200)),
            _ => None,''')

    # ── 2. `push_relic`：拾取副作用
    s = patch(s, '''            RelicEffect::PickupPick(change, picks) => {
                self.pickup_change = Some(change);
                self.pickup_picks = picks;
            }''', '''            RelicEffect::PickupPick(change, picks) => {
                self.pickup_change = Some(change);
                self.pickup_picks = picks;
            }
            // §292：`dollys_mirror` —— 复制一张（同一条欠账通道：`Duplicate` 是"选下标"的编辑）。
            RelicEffect::PickupDuplicate(picks) => {
                self.pickup_change = Some(DeckChange::Duplicate);
                self.pickup_picks = picks;
            }
            // §292：`calling_bell` —— 诅咒**当场**进牌组（牌池在这里就有，`omamori` 该挡就挡），
            // 遗物记成欠账（遗物池在调用方手里）。
            RelicEffect::PickupCurseAndRelics { curse, relics } => {
                // 诅咒必须是**这张镜像里真的存在**的诅咒：拼错的 id 会变成一张幽灵卡，直到
                // 某场战斗抽到它才暴露（与 `GainCurse` 同一条理由）。
                let Some(row) = pool.iter().find(|card| card.id == curse) else {
                    return Err(RunError::NoSuchCard);
                };
                if row.rarity != Rarity::Curse {
                    return Err(RunError::NoSuchCard);
                }
                self.push_card(PoolCard { kind: CardKind::Curse, ..*row })?;
                self.pickup_relics = self.pickup_relics.saturating_add(relics);
            }
            // §292：`cauldron` —— 5 瓶药水记成欠账。
            RelicEffect::PickupPotions(count) => {
                self.pickup_potions = self.pickup_potions.saturating_add(count);
            }
            // §292：宝箱的那两件计数器。
            RelicEffect::ChestExtraRelic { chests } => self.chest_extra = chests,
            RelicEffect::NextChestEmpty(chests) => self.chest_empty = chests,'''
    )

    # ── 3. `push_relic` 的"拿到不生效"清单：新变体里剩下的那些
    s = patch(s, '''            | RelicEffect::PickupPick(_, _)
            | RelicEffect::RestCardReward => {}''', '''            | RelicEffect::PickupPick(_, _)
            // §292：这几件同样不是"拿到就生效" —— 它们分别在战斗结束（`face_of_cleric`）、
            // 奖励掷骰（`nloths_gift`）、药水结算（`sacred_bark`）和**第二半**（`cursed_key`）
            // 上兑现，以及"没有效果"。
            | RelicEffect::Nothing
            | RelicEffect::EndOfCombatMaxHealthUp(_)
            | RelicEffect::ChestAddsCurse
            | RelicEffect::RareCardChanceMultiplier(_)
            | RelicEffect::PotionEffectPercent(_)
            | RelicEffect::RestCardReward => {}''')

    # ── 4. `end_of_combat`：`face_of_cleric`
    s = patch(s, '''                Some(RelicEffect::EndOfCombatHealIfBelow { percent, amount }) => {''',
                  '''                // §292：`face_of_cleric` —— 上限 +1（当前血跟着涨 1，与 `MaxHealthUp`
                // 同一条规矩）。它**不计入** `healed`：涨上限不是治疗，返回值是"这一场回了多少"。
                Some(RelicEffect::EndOfCombatMaxHealthUp(amount)) => {
                    self.health_max += amount;
                    self.adjust_health(amount);
                }
                Some(RelicEffect::EndOfCombatHealIfBelow { percent, amount }) => {''')
    # 并把它从 end_of_combat 的"不是回合末效果"清单里摘掉（上面已经处理了）
    s = patch(s, '''                    | RelicEffect::PickupPick(_, _)
                    | RelicEffect::RestCardReward,
                ) => {}''', '''                    | RelicEffect::PickupPick(_, _)
                    // §292：新变体里的这些同样不是回合末效果（`EndOfCombatMaxHealthUp` 在上面）。
                    | RelicEffect::Nothing
                    | RelicEffect::ChestExtraRelic { .. }
                    | RelicEffect::NextChestEmpty(_)
                    | RelicEffect::ChestAddsCurse
                    | RelicEffect::PickupCurseAndRelics { .. }
                    | RelicEffect::PickupPotions(_)
                    | RelicEffect::PickupDuplicate(_)
                    | RelicEffect::RareCardChanceMultiplier(_)
                    | RelicEffect::PotionEffectPercent(_)
                    | RelicEffect::RestCardReward,
                ) => {}''')

    # ── 5. `DeckChange::Duplicate`
    s = patch(s, '''    /// §274：`astrolabe` —— 改造，**然后**升级改造出来的那张（wiki："Transform 3 cards, then
    /// Upgrade them"）。一个变体而不是"两次编辑"：两次编辑之间那张牌可能已经不在原位。
    TransformAndUpgrade,
}''', '''    /// §274：`astrolabe` —— 改造，**然后**升级改造出来的那张（wiki："Transform 3 cards, then
    /// Upgrade them"）。一个变体而不是"两次编辑"：两次编辑之间那张牌可能已经不在原位。
    TransformAndUpgrade,
    /// §292：`dollys_mirror` —— **复制**这一张（wiki: *"obtain an additional copy of a card in
    /// your deck"*）。牌组满了 ⇒ `push_card` 的 `Capacity`（响亮，不静默丢牌）。
    Duplicate,
}''')
    s = patch(s, '''    /// The three values, for `PartialEq`-driven UI code and for tests that want to enumerate.
    pub const ALL: [Self; 3] = [Self::Remove, Self::Upgrade, Self::Transform];''',
                  '''    /// The four values, for `PartialEq`-driven UI code and for tests that want to enumerate.
    pub const ALL: [Self; 4] = [
        Self::Remove,
        Self::Upgrade,
        Self::Transform,
        Self::TransformAndUpgrade,
    ];''')

    s = patch(s, '''            DeckChange::TransformAndUpgrade => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
                let last = self.deck_len as usize - 1;
                self.upgrade_at(last, pool)?;
            }
        }''', '''            DeckChange::TransformAndUpgrade => {
                self.remove_at(index);
                self.grant_random_cards(1, pool)?;
                let last = self.deck_len as usize - 1;
                self.upgrade_at(last, pool)?;
            }
            // §292：`dollys_mirror` —— 复制那一行（**下标不动**：原件留着，副本进末尾）。
            // 用池子里那一行而不是"id + `+`"推断，理由与 `upgrade_at` 相同：`+` 是内容的事。
            DeckChange::Duplicate => {
                let id = self.deck[index].as_str();
                let Some(row) = pool.iter().find(|card| card.id == id) else {
                    return Err(RunError::NoSuchCard);
                };
                let copy = *row;
                self.push_card(copy)?;
            }
        }''')

    # ── 6. 稀有档倍率（`nloths_gift`）
    s = patch(s, '''            let (rare_top, uncommon_top) = reward_bands(kind, self.rarity_offset);''',
                  '''            // §292：`nloths_gift` —— "Triples the chance of finding Rare cards"。
            // 乘的是**稀有档的宽度**（`reward_bands` 的第一段），并且夹在非稀有档的下界：
            // 稀有档比普通档还宽就不是"更常见稀有牌"而是"奖励几乎全是稀有牌"了。
            let (mut rare_top, uncommon_top) = reward_bands(kind, self.rarity_offset);
            let rare_mult = self.rare_chance_multiplier();
            rare_top = (rare_top * rare_mult / 100).min(uncommon_top);''')

    io.open(STATE, 'w', encoding='utf-8', newline='\n').write(s)
    print('hooks done')


main()
