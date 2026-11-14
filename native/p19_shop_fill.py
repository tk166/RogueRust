"""§377 补丁 2：**补位**那一半也要掷稀有度档位。

第一次改只动了"2 攻 / 2 技 / 1 能力"那条主路径，结果统计测试立刻抓到：Rare 仍然是 **20%** ——
因为池子里缺某一类时，剩下的货位走的是"补位"分支，而那一支是**在全部非无色牌里均匀洗牌**。
这正是"守卫装在了切口下游"的反面：主路径改了，另一条产同一件事的路径没改。

修法：补位时同样先掷档位（`shop_bands`），在（该档位）里取；空了再退到任意档位。
"""

import io

PATH = 'kernel/rd-run/src/state.rs'
t = io.open(PATH, encoding='utf-8').read()

OLD = '''        // 分类不足时**补位**：内容里某一类（通常是 Power）不够 2 张、或池子里的牌没有类型标签时，
        // 从其余的**非无色**牌里补齐。空着整排不是"更忠实"，而是"商店没东西卖"。
        if shelved_cards < MAX_SHOP_CARDS {
            let mut rest = [0u8; MAX_POOL];
            let mut found = 0usize;
            for (index, card) in card_pool.iter().enumerate() {
                if card.colorless {
                    continue;
                }
                let already = self.shop.cards[..shelved_cards]
                    .iter()
                    .any(|offer| offer.id.as_str() == card.id);
                if already {
                    continue;
                }
                if found == MAX_POOL {
                    return Err(RunError::EmptyPool("cards"));
                }
                rest[found] = index as u8;
                found += 1;
            }
            let mut pos = [0u8; MAX_POOL];
            for (slot, entry) in pos.iter_mut().take(found).enumerate() {
                *entry = slot as u8;
            }
            self.rng.shuffle(RunStream::Shop, &mut pos[..found]);
            for slot in 0..found {
                if shelved_cards == MAX_SHOP_CARDS {
                    break;
                }
                let card = card_pool[rest[pos[slot] as usize] as usize];
                let (low, high) = card_price_band(card.rarity);
                let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
                self.shop.cards[shelved_cards] = Offer {
                    id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
                    price: self.marked_up(price),
                };
                shelved_cards += 1;
            }
        }'''

NEW = '''        // 分类不足时**补位**：内容里某一类（通常是 Power）不够 2 张、或池子里的牌没有类型标签时，
        // 从其余的**非无色**牌里补齐。空着整排不是"更忠实"，而是"商店没东西卖"。
        //
        // ⚠️ 补位**也必须掷档位**：第一版只给"2 攻 / 2 技 / 1 能力"那条主路径加了稀有度 roll，
        // 补位仍然是"在全部非无色牌里均匀洗牌" —— 于是池子缺某一类时（测试夹具就是这种池子）
        // Rare 的实际占比又回到"池子里的占比"（实测 20%）。统计测试当场抓到。
        while shelved_cards < MAX_SHOP_CARDS {
            let (rare_top, uncommon_top) = shop_bands(self.rarity_offset);
            let roll = self.rng.roll(RunStream::Shop, 100)? as i32;
            let band = if roll < rare_top {
                Rarity::Rare
            } else if roll < uncommon_top {
                Rarity::Uncommon
            } else {
                Rarity::Common
            };
            // 先在本档位里找；没有就退到任意档位（"总得上一张货"，见上一条注释）。
            let mut picked: Option<usize> = None;
            for wanted in [Some(band), None] {
                let mut members = [0u8; MAX_POOL];
                let mut found = 0usize;
                for (index, card) in card_pool.iter().enumerate() {
                    if card.colorless {
                        continue;
                    }
                    if wanted.is_some_and(|rarity| card.rarity != rarity) {
                        continue;
                    }
                    if self.shop.cards[..shelved_cards]
                        .iter()
                        .any(|offer| offer.id.as_str() == card.id)
                    {
                        continue;
                    }
                    if found == MAX_POOL {
                        return Err(RunError::EmptyPool("cards"));
                    }
                    members[found] = index as u8;
                    found += 1;
                }
                if found > 0 {
                    let pick = self.rng.roll(RunStream::Shop, found as u32)? as usize;
                    picked = Some(members[pick] as usize);
                    break;
                }
            }
            let Some(index) = picked else {
                break; // 池子真的空了：留空格，交给调用方的空货位语义
            };
            let card = card_pool[index];
            let (low, high) = card_price_band(card.rarity);
            let price = low + self.rng.roll(RunStream::Shop, (high - low + 1) as u32)? as i32;
            self.shop.cards[shelved_cards] = Offer {
                id: RunId::new(card.id).map_err(|_| RunError::BadId)?,
                price: self.marked_up(price),
            };
            shelved_cards += 1;
        }'''

assert t.count(OLD) == 1
t = t.replace(OLD, NEW)

# 顺手修测试里我算错的那个期望值：banded = 9-20 = -11 ⇒ 稀有 0、Uncommon 0+37-11 = 26。
OLD_T = '''        assert_eq!(shop_bands(-20), (0, 17), "the rare band floors at 0 and uncommon slides down");'''
NEW_T = '''        // banded = 9 - 20 = -11 ⇒ 稀有夹到 0、Uncommon = 0 + 37 - 11 = 26（宽度不变，整体下移）。
        assert_eq!(shop_bands(-20), (0, 26), "the rare band floors at 0 and uncommon slides down");'''
assert t.count(OLD_T) == 1
t = t.replace(OLD_T, NEW_T)

io.open(PATH, 'w', encoding='utf-8', newline='\n').write(t)
print('补位也掷档位 + 修正测试期望值')
